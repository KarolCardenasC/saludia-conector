"""Validación de datos (paso 4): obligatorios, CIE-10 y coherencia.

Los registros con error se MARCAN y se reportan. No se borran, no se
corrigen y no generan RDA (decisión de diseño 5, sección 4.4).
Este módulo no conoce ni lee la lista de errores sembrados.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .catalogo import CatalogoCIE10
from .modelo import (CAMPO_VACIO, CAMPOS_OBLIGATORIOS, CIE10_INEXISTENTE,
                     CIE10_NO_HABILITADO, FECHA_INCOHERENTE, ID_DUPLICADO, AtencionComun)

FORMATO_SISPRO = re.compile(r"[A-Z][0-9]{2}[0-9X]")
EDAD_MAXIMA = 120


def _como_fecha(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    return v


def validar(at: AtencionComun, catalogo: CatalogoCIE10) -> AtencionComun:
    ya_marcados = {h.campo for h in at.hallazgos}

    for campo in CAMPOS_OBLIGATORIOS:
        if getattr(at, campo) is None and campo not in ya_marcados:
            crudo = at.crudo.get(campo)
            at.agregar(campo, CAMPO_VACIO, "" if crudo is None else crudo,
                       f"El campo obligatorio '{campo}' está vacío")

    cod = at.codigo_cie10
    if cod is not None and cod not in catalogo:
        if cod in catalogo.no_habilitados:
            at.agregar("codigo_cie10", CIE10_NO_HABILITADO, cod,
                       f"El código '{cod}' existe pero no está habilitado en el catálogo")
        elif not FORMATO_SISPRO.fullmatch(cod):
            at.agregar("codigo_cie10", CIE10_INEXISTENTE, cod,
                       f"'{cod}' no tiene el formato CIE-10 de SISPRO (letra + 3 caracteres, "
                       f"sin punto) y no está en el catálogo")
        else:
            at.agregar("codigo_cie10", CIE10_INEXISTENTE, cod,
                       f"El código '{cod}' no existe en el catálogo CIE-10")

    nac, aten = at.fecha_nacimiento, _como_fecha(at.fecha_atencion)
    if nac and aten:
        if nac > aten:
            at.agregar("fecha_nacimiento", FECHA_INCOHERENTE, nac.isoformat(),
                       "La fecha de nacimiento es posterior a la fecha de atención")
        elif (aten.year - nac.year) > EDAD_MAXIMA:
            at.agregar("fecha_nacimiento", FECHA_INCOHERENTE, nac.isoformat(),
                       f"La edad calculada supera {EDAD_MAXIMA} años")
    return at


def marcar_duplicados(atenciones: list[AtencionComun]) -> None:
    """Un mismo id_atencion repetido en la misma fuente se marca (desde la 2.ª vez)."""
    vistos: dict[tuple[str, str], int] = {}
    for at in atenciones:
        if not at.id_atencion:
            continue
        clave = (at.fuente, at.id_atencion)
        if clave in vistos:
            at.agregar("id_atencion", ID_DUPLICADO, at.id_atencion,
                       f"El id '{at.id_atencion}' ya apareció en la fila {vistos[clave]}")
        else:
            vistos[clave] = at.fila
