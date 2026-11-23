"""Carga y validación de los archivos de mapeo YAML (paso 2 del flujo).

Un archivo de mapeo describe una fuente completa: dónde está, cómo se
lee, qué columna corresponde a cada campo del modelo común, en qué
formato vienen las fechas y cómo se traducen los códigos propios de la
fuente. Conectar una fuente nueva = escribir uno de estos archivos.
"""
from __future__ import annotations

import codecs
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .modelo import (CAMPOS_MODELO, CAMPOS_OBLIGATORIOS, SEXOS_VALIDOS,
                     TIPOS_DOCUMENTO_VALIDOS, ErrorConfiguracion)

VERSION_ESQUEMA = 1
TIPOS_FUENTE = ("csv", "excel", "sqlite")
CAMPOS_FECHA = ("fecha_nacimiento", "fecha_atencion", "hora_atencion")
VACIOS_POR_DEFECTO = ["", "NULL", "null"]

CLAVES = {
    "raiz": {"version_esquema", "fuente", "lectura", "columnas", "formatos_fecha",
             "equivalencias", "valores_fijos", "opciones"},
    "fuente": {"id", "nombre", "tipo", "ruta"},
    "lectura": {"separador", "codificacion", "fila_encabezado", "filas_pie", "hoja",
                "tabla", "consulta", "comillas"},
    "equivalencias": {"sexo", "tipo_documento"},
    "opciones": {"valores_vacios", "cie10_quitar_punto", "cie10_completar_x"},
}
LECTURA_POR_TIPO = {
    "csv": {"separador", "codificacion", "fila_encabezado", "filas_pie", "comillas"},
    "excel": {"hoja", "fila_encabezado", "filas_pie"},
    "sqlite": {"tabla", "consulta"},
}


@dataclass
class ConfigFuente:
    id: str
    nombre: str
    tipo: str
    ruta: Path
    archivo_mapeo: Path
    columnas: dict[str, str]
    formatos_fecha: dict[str, list[str]]
    equivalencias: dict[str, dict[str, str]]
    valores_fijos: dict[str, str]
    separador: str = ","
    codificacion: str = "utf-8"
    comillas: str = '"'
    fila_encabezado: int = 1
    filas_pie: int = 0
    hoja: str | int | None = None
    tabla: str | None = None
    consulta: str | None = None
    valores_vacios: list[str] = field(default_factory=lambda: list(VACIOS_POR_DEFECTO))
    cie10_quitar_punto: bool = False
    cie10_completar_x: bool = False


def _sugerir(clave: str, posibles) -> str:
    cerca = difflib.get_close_matches(str(clave), list(posibles), n=1, cutoff=0.6)
    return f" ¿Quisiste decir '{cerca[0]}'?" if cerca else ""


def _revisar_claves(bloque: dict, permitidas: set, donde: str, problemas: list) -> None:
    for k in bloque:
        if k not in permitidas:
            problemas.append(f"En '{donde}' la clave '{k}' no existe.{_sugerir(k, permitidas)}")


def _como_lista(valor) -> list:
    return valor if isinstance(valor, list) else [valor]


def _texto_clave(k: Any, donde: str, problemas: list) -> str:
    # En YAML, palabras como NO, yes, on, off se leen como verdadero/falso
    if isinstance(k, bool):
        problemas.append(f"En '{donde}' hay una clave que YAML leyó como verdadero/falso "
                         f"({k}). Escríbela entre comillas, por ejemplo \"NO\".")
    return str(k).strip()


def cargar_mapeo(archivo: Path, raiz: Path) -> ConfigFuente:
    archivo = Path(archivo)
    try:
        with open(archivo, encoding="utf-8") as f:
            datos = yaml.safe_load(f)
    except FileNotFoundError:
        raise ErrorConfiguracion(f"No existe el archivo de mapeo {archivo}") from None
    except yaml.YAMLError as e:
        raise ErrorConfiguracion(f"{archivo.name} no es un YAML válido: {e}") from None
    except UnicodeDecodeError:
        raise ErrorConfiguracion(f"{archivo.name} debe guardarse en UTF-8") from None
    if not isinstance(datos, dict):
        raise ErrorConfiguracion(f"{archivo.name} está vacío o no tiene la estructura esperada")

    p: list[str] = []
    _revisar_claves(datos, CLAVES["raiz"], "raíz del archivo", p)

    if datos.get("version_esquema") != VERSION_ESQUEMA:
        p.append(f"'version_esquema' debe ser {VERSION_ESQUEMA}")

    # --- fuente -------------------------------------------------------
    fuente = datos.get("fuente") or {}
    if not isinstance(fuente, dict):
        fuente = {}
        p.append("'fuente' debe ser un bloque con id, tipo y ruta")
    _revisar_claves(fuente, CLAVES["fuente"], "fuente", p)
    id_ = str(fuente.get("id", "")).strip()
    if not re.fullmatch(r"[a-z0-9_]+", id_):
        p.append("'fuente.id' es obligatorio y solo admite minúsculas, números y guion bajo")
    tipo = str(fuente.get("tipo", "")).strip().lower()
    if tipo not in TIPOS_FUENTE:
        p.append(f"'fuente.tipo' debe ser uno de {', '.join(TIPOS_FUENTE)}")
    ruta_txt = fuente.get("ruta")
    ruta = None
    if not ruta_txt:
        p.append("'fuente.ruta' es obligatoria")
    else:
        ruta = Path(str(ruta_txt))
        ruta = ruta if ruta.is_absolute() else (raiz / ruta)
        if not ruta.exists():
            p.append(f"No se encuentra el archivo de la fuente: {ruta_txt}")

    # --- lectura ------------------------------------------------------
    lectura = datos.get("lectura") or {}
    if not isinstance(lectura, dict):
        lectura = {}
        p.append("'lectura' debe ser un bloque de opciones")
    _revisar_claves(lectura, CLAVES["lectura"], "lectura", p)
    if tipo in LECTURA_POR_TIPO:
        sobran = set(lectura) - LECTURA_POR_TIPO[tipo]
        for k in sorted(sobran & CLAVES["lectura"]):
            p.append(f"En 'lectura', '{k}' no aplica a fuentes de tipo {tipo}")
    sep = lectura.get("separador", ",")
    if isinstance(sep, str) and sep.lower() in ("tab", "\\t", "tabulador"):
        sep = "\t"
    if not isinstance(sep, str) or len(sep) != 1:
        p.append("'lectura.separador' debe ser un solo carácter (por ejemplo ',' o ';' o tab)")
    cod = str(lectura.get("codificacion", "utf-8"))
    try:
        codecs.lookup(cod)
    except LookupError:
        p.append(f"Codificación desconocida: '{cod}' (ejemplos: utf-8, latin-1, cp1252)")
    fila_enc = lectura.get("fila_encabezado", 1)
    if not isinstance(fila_enc, int) or isinstance(fila_enc, bool) or fila_enc < 1:
        p.append("'lectura.fila_encabezado' debe ser un número entero ≥ 1")
    filas_pie = lectura.get("filas_pie", 0)
    if not isinstance(filas_pie, int) or isinstance(filas_pie, bool) or filas_pie < 0:
        p.append("'lectura.filas_pie' debe ser un número entero ≥ 0")
    if tipo == "sqlite":
        tabla, consulta = lectura.get("tabla"), lectura.get("consulta")
        if bool(tabla) == bool(consulta):
            p.append("En SQLite indica 'tabla' o 'consulta' (solo una de las dos)")
        if tabla and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(tabla)):
            p.append("'lectura.tabla' tiene caracteres no permitidos")
        if consulta and not str(consulta).strip().lower().startswith("select"):
            p.append("'lectura.consulta' solo puede ser una consulta SELECT")

    # --- columnas -----------------------------------------------------
    columnas_raw = datos.get("columnas") or {}
    columnas: dict[str, str] = {}
    if not isinstance(columnas_raw, dict):
        p.append("'columnas' debe ser una lista de campo_del_modelo: nombre_de_columna")
        columnas_raw = {}
    for campo, col in columnas_raw.items():
        if campo not in CAMPOS_MODELO:
            p.append(f"En 'columnas', '{campo}' no es un campo del modelo común."
                     f"{_sugerir(campo, CAMPOS_MODELO)}")
            continue
        if col is None or str(col).strip() == "":
            p.append(f"En 'columnas', falta el nombre de la columna para '{campo}'")
            continue
        columnas[campo] = str(col).strip()

    fijos_raw = datos.get("valores_fijos") or {}
    valores_fijos: dict[str, str] = {}
    if not isinstance(fijos_raw, dict):
        p.append("'valores_fijos' debe ser campo: valor")
        fijos_raw = {}
    for campo, val in fijos_raw.items():
        if campo not in CAMPOS_MODELO:
            p.append(f"En 'valores_fijos', '{campo}' no es un campo del modelo común."
                     f"{_sugerir(campo, CAMPOS_MODELO)}")
        elif campo in columnas:
            p.append(f"'{campo}' está en 'columnas' y en 'valores_fijos'; deja solo uno")
        else:
            valores_fijos[campo] = _texto_clave(val, "valores_fijos", p)

    for campo in CAMPOS_OBLIGATORIOS:
        if campo not in columnas and campo not in valores_fijos:
            p.append(f"Falta mapear el campo obligatorio '{campo}' en 'columnas'")
    if "nombre_completo" in columnas and ({"nombres", "apellidos"} & set(columnas)):
        p.append("Usa 'nombre_completo' o 'nombres'/'apellidos', no ambos")

    # --- formatos de fecha --------------------------------------------
    formatos_raw = datos.get("formatos_fecha") or {}
    formatos: dict[str, list[str]] = {}
    if not isinstance(formatos_raw, dict):
        p.append("'formatos_fecha' debe ser campo: formato")
        formatos_raw = {}
    for campo, fmt in formatos_raw.items():
        if campo not in CAMPOS_FECHA:
            p.append(f"En 'formatos_fecha', '{campo}' no es un campo de fecha u hora."
                     f"{_sugerir(campo, CAMPOS_FECHA)}")
            continue
        lista = [str(x) for x in _como_lista(fmt)]
        for x in lista:
            if "%" not in x:
                p.append(f"Formato de fecha '{x}' sin códigos %, por ejemplo %d/%m/%Y")
        formatos[campo] = lista
    for campo in CAMPOS_FECHA:
        if campo in columnas and campo not in formatos:
            p.append(f"Falta el formato en 'formatos_fecha' para '{campo}'")

    # --- equivalencias ------------------------------------------------
    eq_raw = datos.get("equivalencias") or {}
    equivalencias: dict[str, dict[str, str]] = {}
    if not isinstance(eq_raw, dict):
        p.append("'equivalencias' debe tener los bloques sexo y/o tipo_documento")
        eq_raw = {}
    _revisar_claves(eq_raw, CLAVES["equivalencias"], "equivalencias", p)
    destinos = {"sexo": SEXOS_VALIDOS, "tipo_documento": TIPOS_DOCUMENTO_VALIDOS}
    for campo in ("sexo", "tipo_documento"):
        tabla = eq_raw.get(campo)
        if tabla is None:
            continue
        if not isinstance(tabla, dict) or not tabla:
            p.append(f"'equivalencias.{campo}' debe ser una lista valor_fuente: valor_estándar")
            continue
        conv = {}
        for k, v in tabla.items():
            k_txt = _texto_clave(k, f"equivalencias.{campo}", p)
            v_txt = _texto_clave(v, f"equivalencias.{campo}", p).upper()
            if v_txt not in destinos[campo]:
                p.append(f"En 'equivalencias.{campo}', '{v}' no es un valor estándar. "
                         f"Usa uno de: {', '.join(destinos[campo])}")
            conv[k_txt.casefold()] = v_txt
        equivalencias[campo] = conv

    # --- opciones -----------------------------------------------------
    opciones = datos.get("opciones") or {}
    if not isinstance(opciones, dict):
        p.append("'opciones' debe ser un bloque de opciones")
        opciones = {}
    _revisar_claves(opciones, CLAVES["opciones"], "opciones", p)
    vacios = opciones.get("valores_vacios", VACIOS_POR_DEFECTO)
    if not isinstance(vacios, list):
        p.append("'opciones.valores_vacios' debe ser una lista, por ejemplo [\"\", \"N/A\"]")
        vacios = VACIOS_POR_DEFECTO
    for k in ("cie10_quitar_punto", "cie10_completar_x"):
        if k in opciones and not isinstance(opciones[k], bool):
            p.append(f"'opciones.{k}' debe ser true o false")

    if p:
        lista = "\n  - ".join(p)
        raise ErrorConfiguracion(f"El mapeo {archivo.name} tiene {len(p)} problema(s):\n  - {lista}")

    return ConfigFuente(
        id=id_, nombre=str(fuente.get("nombre") or id_), tipo=tipo, ruta=ruta,
        archivo_mapeo=archivo, columnas=columnas, formatos_fecha=formatos,
        equivalencias=equivalencias, valores_fijos=valores_fijos,
        separador=sep, codificacion=cod, comillas=str(lectura.get("comillas", '"')),
        fila_encabezado=fila_enc, filas_pie=filas_pie,
        hoja=lectura.get("hoja"), tabla=lectura.get("tabla"), consulta=lectura.get("consulta"),
        valores_vacios=[str(v) for v in vacios],
        cie10_quitar_punto=bool(opciones.get("cie10_quitar_punto", False)),
        cie10_completar_x=bool(opciones.get("cie10_completar_x", False)),
    )


def descubrir_mapeos(carpeta: Path) -> list[Path]:
    """Archivos de mapeo en la carpeta (los que empiezan por _ son plantillas)."""
    return sorted(a for a in Path(carpeta).glob("*.y*ml") if not a.name.startswith("_"))
