"""Orquestación del flujo completo (pasos 1 a 7) para una o varias fuentes.

Por cada atención: mapeo → normalización → validación de datos →
(si es válida) Bundle RDA → validación estructural → archivo JSON.
El tiempo por atención (C4) se mide con time.perf_counter() desde que
el registro sale del adaptador hasta que su RDA queda escrito, más la
parte proporcional del tiempo de lectura del archivo de su fuente.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml

from .adaptadores import ResultadoLectura, leer_fuente
from .catalogo import CatalogoCIE10, cargar_catalogo
from .integridad import sha256_archivo
from .mapeo import ConfigFuente, cargar_mapeo, descubrir_mapeos
from .modelo import ID_DUPLICADO, AtencionComun, ErrorConfiguracion
from .motor_fhir import ContextoRDA, construir_bundle, zona_desde_texto
from .normalizador import mapear, normalizar
from .validacion_fhir import VERSION_FHIR, ResultadoValidacion, validar_bundle
from .validador import validar

RAIZ = Path(__file__).resolve().parent.parent


@dataclass
class ResultadoRegistro:
    atencion: AtencionComun
    bundle: dict | None = None
    validacion: ResultadoValidacion | None = None
    archivo_rda: str | None = None
    segundos: float = 0.0


@dataclass
class ResultadoFuente:
    id: str
    nombre: str
    tipo: str
    archivo_mapeo: str
    archivo_fuente: str
    conectada: bool = False
    error_configuracion: str | None = None
    lectura: ResultadoLectura | None = None
    registros: list[ResultadoRegistro] = field(default_factory=list)
    segundos_lectura: float = 0.0
    huella_antes: str | None = None
    huella_despues: str | None = None

    @property
    def intacta(self) -> bool | None:
        if self.huella_antes is None or self.huella_despues is None:
            return None
        return self.huella_antes == self.huella_despues


@dataclass
class ResultadoCorrida:
    inicio: datetime
    fuentes: list[ResultadoFuente]
    catalogo_origen: str
    catalogo_codigos: int
    version_fhir: str = VERSION_FHIR
    segundos_total: float = 0.0
    dir_salidas: Path | None = None

    def registros(self):
        for f in self.fuentes:
            yield from f.registros


def cargar_parametros(raiz: Path = RAIZ) -> dict:
    with open(raiz / "config" / "parametros.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _nombre_archivo(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", texto)[:80] or "sin_id"


def procesar_fuente(cfg: ConfigFuente, catalogo: CatalogoCIE10, ctx: ContextoRDA,
                    dir_salidas: Path | None, progreso: Callable | None = None) -> ResultadoFuente:
    rf = ResultadoFuente(cfg.id, cfg.nombre, cfg.tipo, cfg.archivo_mapeo.name, cfg.ruta.name)
    rf.huella_antes = sha256_archivo(cfg.ruta)
    try:
        t0 = time.perf_counter()
        lectura = leer_fuente(cfg)                         # paso 1
        rf.segundos_lectura = time.perf_counter() - t0
    except ErrorConfiguracion as e:
        rf.error_configuracion = str(e)
        rf.huella_despues = sha256_archivo(cfg.ruta)
        return rf
    rf.conectada, rf.lectura = True, lectura
    n = len(lectura.registros)
    prorrateo = rf.segundos_lectura / n if n else 0.0
    vistos: dict[str, int] = {}
    dir_ok = dir_mal = None
    if dir_salidas is not None:
        dir_ok = dir_salidas / "rda" / cfg.id
        dir_mal = dir_salidas / "rda_rechazados" / cfg.id

    for i, reg in enumerate(lectura.registros, start=1):
        t = time.perf_counter()
        at = mapear(reg, cfg, lectura.columnas_usadas)     # paso 2 → modelo común
        normalizar(at, cfg)                                # paso 3
        validar(at, catalogo)                              # paso 4
        if at.id_atencion:
            if at.id_atencion in vistos:
                at.agregar("id_atencion", ID_DUPLICADO, at.id_atencion,
                           f"El id '{at.id_atencion}' ya apareció en la fila {vistos[at.id_atencion]}")
            else:
                vistos[at.id_atencion] = at.fila
        rr = ResultadoRegistro(at)
        if at.valida:
            rr.bundle = construir_bundle(at, catalogo, ctx)  # paso 5
            rr.validacion = validar_bundle(rr.bundle)        # paso 6
            destino = dir_ok if rr.validacion.valido else dir_mal
            if destino is not None:                          # paso 7
                destino.mkdir(parents=True, exist_ok=True)
                ruta = destino / f"{_nombre_archivo(at.id_atencion)}.json"
                ruta.write_text(json.dumps(rr.bundle, ensure_ascii=False, indent=2), encoding="utf-8")
                rr.archivo_rda = str(ruta.relative_to(dir_salidas.parent)) if dir_salidas.parent in ruta.parents else str(ruta)
        rr.segundos = time.perf_counter() - t + prorrateo
        rf.registros.append(rr)
        if progreso:
            progreso(cfg.id, i, n)
    rf.huella_despues = sha256_archivo(cfg.ruta)
    return rf


def seleccionar_mapeos(raiz: Path, carpeta_mapeos: Path, ids: list[str] | None) -> list[tuple[str, Path | None, str | None]]:
    """Devuelve (id, archivo, error) por fuente pedida, sin detener por un YAML malo."""
    disponibles: dict[str, Path] = {}
    errores: dict[str, str] = {}
    for archivo in descubrir_mapeos(carpeta_mapeos):
        try:
            disponibles[cargar_mapeo(archivo, raiz).id] = archivo
        except ErrorConfiguracion as e:
            errores[archivo.stem] = str(e)
    pedidos = ids if ids else list(disponibles)
    salida = []
    for fid in pedidos:
        if fid in disponibles:
            salida.append((fid, disponibles[fid], None))
        elif fid in errores:
            salida.append((fid, None, errores[fid]))
        else:
            salida.append((fid, None, f"No hay un archivo de mapeo en {carpeta_mapeos.name}/ con fuente.id = '{fid}'"))
    return salida


def ejecutar(raiz: Path = RAIZ, ids_fuentes: list[str] | None = None,
             dir_salidas: Path | None = None, limpiar: bool = True,
             progreso: Callable | None = None, al_iniciar_fuente: Callable | None = None) -> ResultadoCorrida:
    t_total = time.perf_counter()
    p = cargar_parametros(raiz)
    rutas = p["rutas"]
    if ids_fuentes is None:
        ids_fuentes = p["experimento"]["fuentes"]
    dir_salidas = dir_salidas or (raiz / rutas["salidas"])
    if limpiar:
        for sub in ("rda", "rda_rechazados"):
            shutil.rmtree(dir_salidas / sub, ignore_errors=True)
    dir_salidas.mkdir(parents=True, exist_ok=True)

    catalogo = cargar_catalogo(raiz, rutas["referencia_cie10_oficial"], rutas["referencia_cie10_subconjunto"])
    zona = zona_desde_texto(p["ips_simulada"]["zona_horaria"])
    inicio = datetime.now(zona)
    ctx = ContextoRDA(p["ips_simulada"]["nombre"], inicio, zona)

    fuentes = []
    for fid, archivo, error in seleccionar_mapeos(raiz, raiz / rutas["mapeos"], ids_fuentes):
        if al_iniciar_fuente:
            al_iniciar_fuente(fid)
        if error:
            fuentes.append(ResultadoFuente(fid, fid, "?", archivo.name if archivo else "-", "-",
                                           error_configuracion=error))
            continue
        cfg = cargar_mapeo(archivo, raiz)
        fuentes.append(procesar_fuente(cfg, catalogo, ctx, dir_salidas, progreso))

    corrida = ResultadoCorrida(inicio, fuentes, catalogo.origen, len(catalogo), dir_salidas=dir_salidas)
    corrida.segundos_total = time.perf_counter() - t_total
    return corrida


# Compatibilidad con la fase 3: pasos 1 a 4 sin RDA
def extraer_atenciones(cfg: ConfigFuente, catalogo: CatalogoCIE10) -> tuple[ResultadoLectura, list[AtencionComun]]:
    from .validador import marcar_duplicados
    lectura = leer_fuente(cfg)
    atenciones = [validar(normalizar(mapear(r, cfg, lectura.columnas_usadas), cfg), catalogo)
                  for r in lectura.registros]
    marcar_duplicados(atenciones)
    return lectura, atenciones
