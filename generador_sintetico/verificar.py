"""Autoverificación de los datos sintéticos (control de calidad del generador).

Relee los tres archivos generados SIN usar el conector y comprueba que:
  1. cada fuente tiene 100 registros y se lee con su formato declarado;
  2. los registros normales son 100 % válidos (cero errores accidentales);
  3. cada registro sembrado falla exactamente en el campo sembrado.

Esto NO mide C3. C3 lo mide el módulo de métricas comparando lo que
reporta el conector contra errores_sembrados.csv.
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from . import generador as g


def _leer_fuente1(ruta: Path) -> list[tuple[int, dict]]:
    cols = g.COLUMNAS[g.FUENTE1]
    con = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
    try:
        sel = ", ".join(cols.values())
        filas = con.execute(f"SELECT rowid, {sel} FROM tb_atencion ORDER BY rowid").fetchall()
    finally:
        con.close()
    return [(f[0], dict(zip(cols.keys(), f[1:]))) for f in filas]


def _leer_fuente2(ruta: Path) -> list[tuple[int, dict]]:
    cols = g.COLUMNAS[g.FUENTE2]
    with open(ruta, encoding="cp1252", newline="") as f:
        lector = csv.DictReader(f, delimiter=",")
        return [(i + 2, {k: fila[v] for k, v in cols.items()}) for i, fila in enumerate(lector)]


def _leer_fuente3(ruta: Path) -> list[tuple[int, dict]]:
    cols = g.COLUMNAS[g.FUENTE3]
    wb = load_workbook(ruta, read_only=True)
    ws = wb["Atenciones"]
    filas = list(ws.iter_rows(min_row=g.EXCEL_FILA_ENCABEZADO, values_only=True))
    wb.close()
    encab = list(filas[0])
    idx = {k: encab.index(v) for k, v in cols.items()}
    salida = []
    for i, fila in enumerate(filas[1:]):
        salida.append((g.EXCEL_FILA_ENCABEZADO + 1 + i, {k: fila[j] for k, j in idx.items()}))
    return salida


LECTORES = {g.FUENTE1: _leer_fuente1, g.FUENTE2: _leer_fuente2, g.FUENTE3: _leer_fuente3}


def _fallas(fuente: str, reg: dict, catalogo: set[str]) -> list[str]:
    fallas = []
    for campo in g.CAMPOS_OBLIGATORIOS:
        v = reg.get(campo)
        if v is None or str(v).strip() == "":
            fallas.append(campo)
    for campo, fmt in g.FORMATO_FECHA[fuente].items():
        v = reg.get(campo)
        if campo in fallas:
            continue
        try:
            datetime.strptime(str(v).strip(), fmt)
        except ValueError:
            fallas.append(campo)
    v = reg.get("codigo_cie10")
    if "codigo_cie10" not in fallas and str(v).strip() not in catalogo:
        fallas.append("codigo_cie10")
    if "sexo" not in fallas and str(reg["sexo"]) not in g.SEXO[fuente].values():
        fallas.append("sexo")
    if "tipo_documento" not in fallas and str(reg["tipo_documento"]) not in g.TIPO_DOC[fuente].values():
        fallas.append("tipo_documento")
    return fallas


def huella_contenido(fuente: str, ruta: Path) -> str:
    """SHA-256 de los registros leídos (no de los bytes del archivo).

    El .xlsx guarda internamente la hora de guardado, así que sus bytes
    cambian en cada generación aunque los datos sean idénticos. Esta
    huella permite demostrar que la semilla reproduce los mismos datos.
    """
    import hashlib
    import json
    regs = LECTORES[fuente](ruta)
    texto = json.dumps([[fila, {k: (None if v is None else str(v)) for k, v in r.items()}]
                        for fila, r in regs], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def verificar(raiz: Path = g.RAIZ) -> dict:
    p = g.cargar_parametros()
    catalogo = set(g.cargar_codigos_catalogo(raiz / p["rutas"]["referencia_cie10_subconjunto"]))
    with open(raiz / p["rutas"]["errores_sembrados"], encoding="utf-8", newline="") as f:
        verdad = list(csv.DictReader(f))
    esperado = {(v["fuente"], int(v["fila"])): v["campo"] for v in verdad}

    resultado = {"ok": True, "detalle": {}, "problemas": []}
    for fuente, lector in LECTORES.items():
        regs = lector(raiz / p["rutas"]["fuentes"] / g.ARCHIVOS[fuente])
        normales_ok = sembrados_ok = 0
        for fila, reg in regs:
            fallas = _fallas(fuente, reg, catalogo)
            clave = (fuente, fila)
            if clave in esperado:
                if fallas == [esperado[clave]]:
                    sembrados_ok += 1
                else:
                    resultado["problemas"].append(
                        f"{fuente} fila {fila}: sembrado en {esperado[clave]}, falla en {fallas}")
            elif fallas:
                resultado["problemas"].append(f"{fuente} fila {fila}: error accidental en {fallas}")
            else:
                normales_ok += 1
        sembrados_fuente = sum(1 for k in esperado if k[0] == fuente)
        resultado["detalle"][fuente] = {
            "registros": len(regs), "normales_validos": normales_ok,
            "sembrados_esperados": sembrados_fuente, "sembrados_que_fallan_bien": sembrados_ok,
        }
    resultado["ok"] = not resultado["problemas"] and all(
        d["registros"] == 100 and d["normales_validos"] == 100 - d["sembrados_esperados"]
        and d["sembrados_que_fallan_bien"] == d["sembrados_esperados"]
        for d in resultado["detalle"].values())
    return resultado
