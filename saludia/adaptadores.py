"""Adaptadores de lectura (paso 1 del flujo).

Leen cada fuente SIEMPRE en solo lectura y entregan filas crudas con
sus columnas originales. No interpretan los datos: eso lo hacen el
normalizador y el validador. Un dato malo nunca detiene la lectura; un
problema de configuración (archivo, hoja, tabla o columna inexistente)
sí impide conectar la fuente y se informa con ErrorConfiguracion.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd

from .mapeo import ConfigFuente
from .modelo import ERROR_LECTURA, ErrorConfiguracion, Hallazgo, RegistroCrudo

MAX_COLUMNAS_CSV = 512


@dataclass
class ResultadoLectura:
    fuente: str
    registros: list[RegistroCrudo]
    columnas_fuente: list[str]
    columnas_usadas: dict[str, str]          # campo_modelo -> columna real
    columnas_ignoradas: list[str]
    avisos: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------
def _limpiar_valor(v: Any) -> Any:
    """Convierte lo que entrega pandas/sqlite a texto, fecha o None."""
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v):
            return None
        return str(int(v)) if v.is_integer() else str(v)
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, (datetime, date)):
        return v
    if isinstance(v, (int,)) and not isinstance(v, bool):
        return str(v)
    return str(v)


def resolver_columnas(cfg: ConfigFuente, disponibles: list[str]) -> tuple[dict[str, str], list[str]]:
    """Empareja las columnas del YAML con las reales (exacto y luego sin mayúsculas)."""
    import difflib
    por_minuscula = {}
    for c in disponibles:
        por_minuscula.setdefault(c.casefold(), c)
    usadas, faltan = {}, []
    for campo, col in cfg.columnas.items():
        if col in disponibles:
            usadas[campo] = col
        elif col.casefold() in por_minuscula:
            usadas[campo] = por_minuscula[col.casefold()]
        else:
            sug = difflib.get_close_matches(col, disponibles, n=1, cutoff=0.5)
            faltan.append(f"'{col}' (para {campo})" + (f" — ¿quisiste decir '{sug[0]}'?" if sug else ""))
    if faltan:
        raise ErrorConfiguracion(
            f"[{cfg.id}] Estas columnas del mapeo no existen en la fuente: {'; '.join(faltan)}.\n"
            f"  Columnas disponibles: {', '.join(disponibles)}")
    ignoradas = [c for c in disponibles if c not in usadas.values()]
    return usadas, ignoradas


def _construir(cfg: ConfigFuente, encabezado: list[str], filas: list[tuple[int, list]]) -> ResultadoLectura:
    encabezado = [str(c).strip() if c is not None else "" for c in encabezado]
    nombrados = [c for c in encabezado if c]
    duplicados = sorted({c for c in nombrados if nombrados.count(c) > 1})
    usadas, ignoradas = resolver_columnas(cfg, nombrados)
    choque = [c for c in duplicados if c in usadas.values()]
    if choque:
        raise ErrorConfiguracion(f"[{cfg.id}] Columnas repetidas en el encabezado: {', '.join(choque)}")
    posicion = {c: encabezado.index(c) for c in usadas.values()}
    registros = []
    for fila, valores in filas:
        reg = RegistroCrudo(fuente=cfg.id, fila=fila, datos={})
        try:
            for col, j in posicion.items():
                reg.datos[col] = _limpiar_valor(valores[j]) if j < len(valores) else None
        except Exception as e:  # nunca detener la lectura por un dato
            reg.hallazgos.append(Hallazgo("(fila)", ERROR_LECTURA, None, f"No se pudo leer la fila: {e}"))
        registros.append(reg)
    return ResultadoLectura(cfg.id, registros, nombrados, usadas, ignoradas)


def _vacia(valores: list) -> bool:
    return all(_limpiar_valor(v) in (None, "") or (isinstance(v, str) and not v.strip())
               for v in valores)


# ---------------------------------------------------------------------
def leer_csv(cfg: ConfigFuente) -> ResultadoLectura:
    try:
        with open(cfg.ruta, "rb") as f:          # modo binario de solo lectura
            df = pd.read_csv(
                f, sep=cfg.separador, encoding=cfg.codificacion, quotechar=cfg.comillas,
                header=None, names=range(MAX_COLUMNAS_CSV), dtype=str,
                keep_default_na=False, skip_blank_lines=False, engine="python")
    except UnicodeDecodeError as e:
        raise ErrorConfiguracion(
            f"[{cfg.id}] No se pudo leer con la codificación '{cfg.codificacion}': {e.reason}. "
            f"Prueba con 'latin-1', 'cp1252' o 'utf-8-sig'.") from None
    except pd.errors.ParserError as e:
        raise ErrorConfiguracion(f"[{cfg.id}] El CSV no se pudo interpretar: {e}") from None
    df = df.dropna(axis=1, how="all")
    todas = [list(r) for r in df.itertuples(index=False, name=None)]
    h = cfg.fila_encabezado - 1
    if h >= len(todas):
        raise ErrorConfiguracion(f"[{cfg.id}] 'fila_encabezado' = {cfg.fila_encabezado}, "
                                 f"pero el archivo solo tiene {len(todas)} filas")
    encabezado = [None if (isinstance(v, float) and math.isnan(v)) else v for v in todas[h]]
    while encabezado and encabezado[-1] in (None, ""):
        encabezado.pop()
    if len(encabezado) == 1 and cfg.separador not in str(encabezado[0]) and len(str(encabezado[0])) > 30:
        raise ErrorConfiguracion(
            f"[{cfg.id}] El encabezado quedó en una sola columna; revisa 'separador' "
            f"(actual: '{cfg.separador}')")
    datos = [(h + 2 + i, fila) for i, fila in enumerate(todas[h + 1:])]
    datos = [d for d in datos if not _vacia(d[1])]
    if cfg.filas_pie:
        datos = datos[:-cfg.filas_pie] if cfg.filas_pie < len(datos) else []
    res = _construir(cfg, encabezado, datos)
    n = len(encabezado)
    for reg, (_, fila) in zip(res.registros, datos):
        presentes = [j for j, v in enumerate(fila) if not (isinstance(v, float) and math.isnan(v))]
        total = (max(presentes) + 1) if presentes else 0
        if total > n:
            reg.hallazgos.append(Hallazgo("(fila)", ERROR_LECTURA, total,
                                          f"La fila tiene {total} campos y el encabezado {n}"))
        elif total < n:
            reg.hallazgos.append(Hallazgo("(fila)", ERROR_LECTURA, total,
                                          f"La fila está incompleta: {total} de {n} campos"))
    return res


def leer_excel(cfg: ConfigFuente) -> ResultadoLectura:
    hoja = 0 if cfg.hoja is None else cfg.hoja
    try:
        with open(cfg.ruta, "rb") as f:          # solo lectura
            libro = pd.ExcelFile(f, engine="openpyxl")
            if isinstance(hoja, str) and hoja not in libro.sheet_names:
                raise ErrorConfiguracion(f"[{cfg.id}] La hoja '{hoja}' no existe. "
                                         f"Hojas: {', '.join(libro.sheet_names)}")
            df = pd.read_excel(libro, sheet_name=hoja, header=None, dtype=object,
                               keep_default_na=False)
    except ErrorConfiguracion:
        raise
    except (ValueError, IndexError, KeyError) as e:
        raise ErrorConfiguracion(f"[{cfg.id}] No se pudo abrir la hoja {hoja!r}: {e}") from None
    todas = [list(r) for r in df.itertuples(index=False, name=None)]
    h = cfg.fila_encabezado - 1
    if h >= len(todas):
        raise ErrorConfiguracion(f"[{cfg.id}] 'fila_encabezado' = {cfg.fila_encabezado}, "
                                 f"pero la hoja solo tiene {len(todas)} filas")
    datos = [(h + 2 + i, fila) for i, fila in enumerate(todas[h + 1:])]
    datos = [d for d in datos if not _vacia(d[1])]
    if cfg.filas_pie:
        datos = datos[:-cfg.filas_pie] if cfg.filas_pie < len(datos) else []
    return _construir(cfg, todas[h], datos)


def abrir_sqlite_solo_lectura(ruta) -> sqlite3.Connection:
    """Conexión en modo solo lectura (mode=ro) y con escritura bloqueada."""
    uri = ruta.resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA query_only = ON")
    return con


def leer_sqlite(cfg: ConfigFuente) -> ResultadoLectura:
    try:
        con = abrir_sqlite_solo_lectura(cfg.ruta)
    except sqlite3.Error as e:
        raise ErrorConfiguracion(f"[{cfg.id}] No se pudo abrir la base de datos: {e}") from None
    try:
        if cfg.tabla:
            tablas = [t for (t,) in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')")]
            if cfg.tabla not in tablas:
                raise ErrorConfiguracion(f"[{cfg.id}] La tabla '{cfg.tabla}' no existe. "
                                         f"Tablas: {', '.join(tablas)}")
            try:
                cur = con.execute(f'SELECT rowid AS "__fila__", * FROM "{cfg.tabla}" ORDER BY rowid')
                con_rowid = True
            except sqlite3.OperationalError:
                cur = con.execute(f'SELECT * FROM "{cfg.tabla}"')
                con_rowid = False
        else:
            try:
                cur = con.execute(cfg.consulta)
            except sqlite3.Error as e:
                raise ErrorConfiguracion(f"[{cfg.id}] La consulta falló: {e}") from None
            con_rowid = False
        nombres = [d[0] for d in cur.description]
        filas = cur.fetchall()
    finally:
        con.close()
    if con_rowid:
        encabezado = nombres[1:]
        datos = [(f[0], list(f[1:])) for f in filas]
    else:
        encabezado = nombres
        datos = [(i + 1, list(f)) for i, f in enumerate(filas)]
    return _construir(cfg, encabezado, datos)


LECTORES = {"csv": leer_csv, "excel": leer_excel, "sqlite": leer_sqlite}


def leer_fuente(cfg: ConfigFuente) -> ResultadoLectura:
    return LECTORES[cfg.tipo](cfg)
