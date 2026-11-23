"""Métricas de los criterios de éxito C1 a C5 (sección 3.3 del informe).

Este es el ÚNICO módulo del conector que lee la lista de errores
sembrados (datos/errores_sembrados.csv), y solo para medir C2 y C3.
El validador nunca la ve.

Las metas se leen de config/metas.yaml; aquí no hay ninguna meta escrita
a mano. Si metas.yaml cambia respecto de su huella registrada
(config/metas.sha256), se informa.
"""
from __future__ import annotations

import csv
import json
import platform
import sqlite3
import statistics
import sys
from datetime import datetime
from pathlib import Path

import yaml
from openpyxl import load_workbook

from .conector import ResultadoCorrida, cargar_parametros
from .integridad import sha256_archivo
from .mapeo import ConfigFuente, cargar_mapeo, descubrir_mapeos
from .validacion_fhir import ALCANCE, VERSION_FHIR


# ---------------------------------------------------------------------
# Metas
# ---------------------------------------------------------------------
def cargar_metas(raiz: Path) -> dict:
    ruta = raiz / "config" / "metas.yaml"
    with open(ruta, encoding="utf-8") as f:
        metas = yaml.safe_load(f)
    actual = sha256_archivo(ruta)
    registrada = None
    ruta_huella = raiz / "config" / "metas.sha256"
    if ruta_huella.exists():
        registrada = ruta_huella.read_text(encoding="utf-8").split()[0]
    metas["_sha256"] = actual
    metas["_sha256_registrada"] = registrada
    metas["_sin_cambios"] = (registrada == actual) if registrada else None
    return metas


def cumple(operador: str, resultado, meta) -> bool | None:
    if resultado is None:
        return None
    if operador == ">=":
        return resultado >= meta
    if operador == "<=":
        return resultado <= meta
    if operador == "si/no":
        return str(resultado).lower() == str(meta).lower()
    raise ValueError(f"Operador desconocido en metas.yaml: {operador}")


# ---------------------------------------------------------------------
# Conteo independiente de registros en la fuente (denominador de C1).
# Usa bibliotecas distintas a las del adaptador (csv/sqlite3/openpyxl
# directos, sin pandas) para que C1 no sea 100 % por construcción.
# ---------------------------------------------------------------------
def _fila_vacia(valores) -> bool:
    return all(v is None or str(v).strip() == "" for v in valores)


def contar_registros_independiente(cfg: ConfigFuente) -> int:
    if cfg.tipo == "sqlite":
        uri = cfg.ruta.resolve().as_uri() + "?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        try:
            if cfg.tabla:
                (n,) = con.execute(f'SELECT COUNT(*) FROM "{cfg.tabla}"').fetchone()
            else:
                (n,) = con.execute(f"SELECT COUNT(*) FROM ({cfg.consulta})").fetchone()
        finally:
            con.close()
        return int(n)
    if cfg.tipo == "csv":
        with open(cfg.ruta, encoding=cfg.codificacion, newline="") as f:
            filas = list(csv.reader(f, delimiter=cfg.separador, quotechar=cfg.comillas))
        datos = [r for r in filas[cfg.fila_encabezado:] if not _fila_vacia(r)]
        return max(0, len(datos) - cfg.filas_pie)
    if cfg.tipo == "excel":
        wb = load_workbook(cfg.ruta, read_only=True, data_only=True)
        try:
            ws = wb[cfg.hoja] if isinstance(cfg.hoja, str) else wb.worksheets[cfg.hoja or 0]
            datos = [r for r in ws.iter_rows(min_row=cfg.fila_encabezado + 1, values_only=True)
                     if not _fila_vacia(r)]
        finally:
            wb.close()
        return max(0, len(datos) - cfg.filas_pie)
    raise ValueError(cfg.tipo)


def conteos_independientes(raiz: Path, ids: list[str]) -> dict[str, int | None]:
    p = cargar_parametros(raiz)
    por_id = {}
    for archivo in descubrir_mapeos(raiz / p["rutas"]["mapeos"]):
        try:
            cfg = cargar_mapeo(archivo, raiz)
        except Exception:
            continue
        if cfg.id in ids:
            try:
                por_id[cfg.id] = contar_registros_independiente(cfg)
            except Exception:
                por_id[cfg.id] = None
    return {i: por_id.get(i) for i in ids}


# ---------------------------------------------------------------------
# Lista de verdad (solo aquí)
# ---------------------------------------------------------------------
def cargar_errores_sembrados(raiz: Path) -> list[dict]:
    p = cargar_parametros(raiz)
    with open(raiz / p["rutas"]["errores_sembrados"], encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class Cruce:
    """Empareja registros con la lista de verdad: por (fuente, id_atencion);
    si el id sembrado está vacío, por (fuente, fila)."""

    def __init__(self, verdad: list[dict]):
        self.por_id = {(v["fuente"], v["id_atencion"]): v for v in verdad if v["id_atencion"]}
        self.por_fila = {(v["fuente"], int(v["fila"])): v for v in verdad if not v["id_atencion"]}

    def buscar(self, fuente: str, id_atencion: str | None, fila: int) -> dict | None:
        if id_atencion and (fuente, id_atencion) in self.por_id:
            return self.por_id[(fuente, id_atencion)]
        if not id_atencion:
            return self.por_fila.get((fuente, fila))
        return None


# ---------------------------------------------------------------------
def _pct(a: int, b: int) -> float | None:
    return round(100.0 * a / b, 2) if b else None


def leer_c5(raiz: Path) -> dict | None:
    ruta = raiz / cargar_parametros(raiz)["rutas"]["salidas"] / "c5.json"
    if not ruta.exists():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def calcular_metricas(corrida: ResultadoCorrida, raiz: Path) -> dict:
    metas = cargar_metas(raiz)
    m = metas["criterios"]
    ids = [f.id for f in corrida.fuentes]
    verdad = [v for v in cargar_errores_sembrados(raiz) if v["fuente"] in ids]
    cruce = Cruce(verdad)
    conteos = conteos_independientes(raiz, ids)
    registros = list(corrida.registros())

    # --- C1 · extracción automática ---------------------------------
    extraidos = {f.id: len(f.registros) for f in corrida.fuentes}
    total_fuente = sum(v for v in conteos.values() if v is not None)
    c1 = _pct(sum(extraidos.values()), total_fuente)

    # --- C2 y C3 · cruce con la verdad --------------------------------
    sembrados_vistos, detectados, detectados_exacto, falsos_positivos = [], [], 0, []
    sin_siembra = sin_siembra_validos = 0
    for rr in registros:
        at = rr.atencion
        v = cruce.buscar(at.fuente, at.id_atencion, at.fila)
        if v is None:
            sin_siembra += 1
            if rr.validacion is not None and rr.validacion.valido:
                sin_siembra_validos += 1
            if not at.valida:
                falsos_positivos.append({"fuente": at.fuente, "fila": at.fila, "id_atencion": at.id_atencion,
                                         "hallazgos": [h.tipo_error for h in at.hallazgos]})
        else:
            sembrados_vistos.append(v)
            if not at.valida:
                detectados.append(v)
                if any(h.tipo_error == v["tipo_error"] and h.campo == v["campo"] for h in at.hallazgos):
                    detectados_exacto += 1
    claves_detectadas = {(v["fuente"], v["fila"]) for v in detectados}
    no_detectados = [v for v in verdad if (v["fuente"], v["fila"]) not in claves_detectadas]
    denominador_c2 = total_fuente - len(verdad)      # 300 − 30 = 270 en el experimento
    c2 = _pct(sin_siembra_validos, denominador_c2)
    c3 = _pct(len(detectados), len(verdad))

    # --- C4 · tiempo por atención -------------------------------------
    tiempos = [rr.segundos for rr in registros]
    c4 = round(statistics.mean(tiempos), 6) if tiempos else None

    # --- C5 · fuente nueva solo con YAML --------------------------------
    c5 = leer_c5(raiz)
    c5_res = c5.get("veredicto") if c5 else None
    c5_cumple = None if c5 is None else (c5_res == "si")

    criterios = {
        "C1": {"resultado": c1, "detalle": {
            "extraidos": sum(extraidos.values()), "en_fuentes_conteo_independiente": total_fuente,
            "por_fuente": {i: {"extraidos": extraidos[i], "en_fuente": conteos[i]} for i in ids},
            "metodo_conteo": "COUNT(*) en SQLite; csv.reader y openpyxl directos (sin pandas) para CSV y Excel",
        }},
        "C2": {"resultado": c2, "detalle": {
            "bundles_validos_sin_error_sembrado": sin_siembra_validos,
            "registros_sin_error_sembrado": denominador_c2,
            "bundles_generados_total": sum(rr.bundle is not None for rr in registros),
            "bundles_validos_total": sum(bool(rr.validacion and rr.validacion.valido) for rr in registros),
            "alcance": ALCANCE,
        }},
        "C3": {"resultado": c3, "detalle": {
            "sembrados": len(verdad), "detectados": len(detectados),
            "detectados_con_tipo_y_campo_correctos": detectados_exacto,
            "no_detectados": no_detectados,
            "falsos_positivos": len(falsos_positivos), "lista_falsos_positivos": falsos_positivos,
            "regla_cruce": "(fuente, id_atencion); si el id está vacío, (fuente, fila)",
        }},
        "C4": {"resultado": c4, "detalle": {
            "promedio_s": c4,
            "mediana_s": round(statistics.median(tiempos), 6) if tiempos else None,
            "maximo_s": round(max(tiempos), 6) if tiempos else None,
            "minimo_s": round(min(tiempos), 6) if tiempos else None,
            "suma_por_registro_s": round(sum(tiempos), 4),
            "total_corrida_s": round(corrida.segundos_total, 4),
            "atenciones": len(tiempos),
            "metodo": "time.perf_counter() por registro, desde la salida del adaptador hasta el RDA "
                      "escrito, más la parte proporcional de la lectura del archivo",
        }},
        "C5": {"resultado": c5_res if c5 else "pendiente", "detalle": c5 or {
            "estado": "pendiente", "nota": "Se mide con scripts/c5_cronometro.py"}},
    }
    for k, c in criterios.items():
        c.update({kk: m[k][kk] for kk in ("nombre", "operador", "meta", "unidad")})
        c["cumplio"] = c5_cumple if k == "C5" else cumple(m[k]["operador"], c["resultado"], m[k]["meta"])

    regla = metas["regla_h2"]
    estados = [criterios[k]["cumplio"] for k in regla]
    if any(e is False for e in estados):
        h2 = "no confirmada"
    elif any(e is None for e in estados):
        h2 = "pendiente"
    else:
        h2 = "confirmada en entorno simulado"

    return {
        "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "leyenda": "Prototipo académico · datos sintéticos · validación estructural FHIR R4",
        "version_fhir": VERSION_FHIR,
        "alcance_validacion": ALCANCE,
        "catalogo_cie10": {"origen": corrida.catalogo_origen, "codigos": corrida.catalogo_codigos},
        "metas": {"archivo": "config/metas.yaml", "fecha_fijacion": metas["fecha_fijacion"],
                  "sha256": metas["_sha256"], "sha256_registrada": metas["_sha256_registrada"],
                  "sin_cambios": metas["_sin_cambios"]},
        "fuentes_intactas": {f.id: f.intacta for f in corrida.fuentes},
        "criterios": criterios,
        "hipotesis_h2": {"regla": f"Se cumplen {', '.join(regla)}", "criterios": regla, "estado": h2},
        "entorno": {"python": sys.version.split()[0], "sistema": platform.platform(),
                    "fhir_resources": __import__("fhir.resources").resources.__version__},
    }


def escribir_metricas(metricas: dict, carpeta: Path) -> Path:
    ruta = carpeta / "metricas.json"
    ruta.write_text(json.dumps(metricas, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def formato_resultado(clave: str, c: dict) -> str:
    r = c["resultado"]
    if r is None:
        return "—"
    if clave == "C4":
        return f"{r:.4f} s"
    if clave == "C5":
        if r == "pendiente":
            return "pendiente"
        seg = (c.get("detalle") or {}).get("segundos")
        return f"{r} ({seg / 60:.1f} min)" if isinstance(seg, (int, float)) else str(r)
    return f"{r:.2f} %"


def formato_meta(c: dict) -> str:
    if c["operador"] == "si/no":
        return "sí, solo YAML"
    if c["operador"] == ">=" and c["unidad"] == "%" and c["meta"] == 100:
        return "= 100 %"
    signo = {">=": "≥", "<=": "≤"}[c["operador"]]
    return f"{signo} {c['meta']:g} {c['unidad']}"
