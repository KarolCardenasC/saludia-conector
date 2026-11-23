"""Catálogo CIE-10 de referencia (tabla de SISPRO o subconjunto transcrito)."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .modelo import ErrorConfiguracion

NO_HABILITADO = {"NO", "N", "0", "FALSE", "FALSO", "INACTIVO"}


@dataclass
class CatalogoCIE10:
    codigos: set[str]
    no_habilitados: set[str] = field(default_factory=set)
    nombres: dict[str, str] = field(default_factory=dict)
    origen: str = ""          # "oficial SISPRO" o "subconjunto transcrito"
    ruta: Path | None = None

    def __contains__(self, codigo: str) -> bool:
        return codigo in self.codigos

    def __len__(self) -> int:
        return len(self.codigos)


def _clave(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return t.strip().casefold()


def _leer_tabla(ruta: Path) -> pd.DataFrame:
    if ruta.suffix.lower() in (".xlsx", ".xlsm"):
        with open(ruta, "rb") as f:
            return pd.read_excel(f, dtype=str, keep_default_na=False, engine="openpyxl")
    ultimo = None
    for cod in ("utf-8-sig", "cp1252"):
        try:
            with open(ruta, "rb") as f:
                return pd.read_csv(f, sep=None, engine="python", dtype=str,
                                   keep_default_na=False, encoding=cod)
        except UnicodeDecodeError as e:
            ultimo = e
    raise ErrorConfiguracion(f"No se pudo leer el catálogo {ruta.name}: {ultimo}")


def cargar_catalogo(raiz: Path, ruta_oficial: str, ruta_subconjunto: str) -> CatalogoCIE10:
    """Usa la tabla oficial de SISPRO si existe; si no, el subconjunto."""
    oficial = raiz / ruta_oficial
    candidatos = [oficial, oficial.with_suffix(".xlsx")]
    ruta = next((c for c in candidatos if c.exists()), None)
    origen = "tabla oficial SISPRO"
    if ruta is None:
        ruta = raiz / ruta_subconjunto
        origen = "subconjunto transcrito (contrastar con SISPRO)"
    if not ruta.exists():
        raise ErrorConfiguracion(f"No se encontró el catálogo CIE-10 en {ruta}")
    df = _leer_tabla(ruta)
    cols = {_clave(c): c for c in df.columns}
    col_cod = cols.get("codigo") or cols.get("cod") or cols.get("code")
    if col_cod is None:
        raise ErrorConfiguracion(
            f"El catálogo {ruta.name} no tiene una columna 'Codigo'. Columnas: {', '.join(df.columns)}")
    col_hab = cols.get("habilitado")
    col_nom = cols.get("nombre") or cols.get("descripcion")
    codigos, no_hab, nombres = set(), set(), {}
    for _, fila in df.iterrows():
        cod = str(fila[col_cod]).strip().upper()
        if not cod:
            continue
        if col_hab and str(fila[col_hab]).strip().upper() in NO_HABILITADO:
            no_hab.add(cod)
            continue
        codigos.add(cod)
        if col_nom:
            nombres[cod] = str(fila[col_nom]).strip()
    return CatalogoCIE10(codigos, no_hab, nombres, origen, ruta)
