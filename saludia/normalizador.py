"""Mapeo al modelo común (paso 2) y normalización de formatos (paso 3).

- Renombra las columnas de la fuente a los campos del modelo común.
- Unifica fechas, sexo, tipo de documento y código CIE-10.
- Si un valor no se puede interpretar, lo MARCA y sigue: nunca lanza
  una excepción por un dato malo y nunca adivina el valor correcto.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time

from .mapeo import ConfigFuente
from .modelo import (CAMPOS_MODELO, ERROR_LECTURA, FECHA_INVALIDA, SEXOS_VALIDOS,
                     TIPOS_DOCUMENTO_VALIDOS, VALOR_NO_RECONOCIDO, AtencionComun,
                     RegistroCrudo)

_LEGIBLE = {"%d": "DD", "%m": "MM", "%Y": "AAAA", "%y": "AA", "%H": "HH", "%M": "MM",
            "%S": "SS", "%I": "hh", "%p": "AM/PM", "%b": "mes abreviado", "%B": "mes"}


def formato_legible(fmt: str) -> str:
    salida = fmt
    for k, v in _LEGIBLE.items():
        salida = salida.replace(k, v)
    return salida


def mapear(reg: RegistroCrudo, cfg: ConfigFuente, columnas_usadas: dict[str, str]) -> AtencionComun:
    """Paso 2: de columnas propias de la fuente a campos del modelo común."""
    at = AtencionComun(fuente=reg.fuente, fila=reg.fila)
    at.hallazgos.extend(reg.hallazgos)
    for campo, col in columnas_usadas.items():
        at.crudo[campo] = reg.datos.get(col)
    for campo, valor in cfg.valores_fijos.items():
        at.crudo[campo] = valor
    return at


def _texto(valor, cfg: ConfigFuente):
    if valor is None:
        return None
    if isinstance(valor, (datetime, date)):
        return valor
    t = " ".join(str(valor).split())
    if t in cfg.valores_vacios or str(valor).strip() in cfg.valores_vacios:
        return None
    return t or None


def _equivalencia(at: AtencionComun, campo: str, valor, cfg: ConfigFuente, validos: dict):
    if valor is None:
        return None
    tabla = cfg.equivalencias.get(campo)
    if tabla is not None:
        destino = tabla.get(str(valor).casefold())
        if destino:
            return destino
        at.agregar(campo, VALOR_NO_RECONOCIDO, valor,
                   f"'{valor}' no está en la tabla de equivalencias de {campo} del mapeo")
        return None
    if str(valor).upper() in validos:
        return str(valor).upper()
    at.agregar(campo, VALOR_NO_RECONOCIDO, valor,
               f"'{valor}' no es un valor estándar de {campo} y el mapeo no define equivalencias")
    return None


def _fecha(at: AtencionComun, campo: str, valor, formatos: list[str]):
    """Devuelve datetime (si el formato trae hora) o date; marca si no se puede."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, date):
        return valor
    motivo_calendario = False
    for fmt in formatos:
        try:
            dt = datetime.strptime(str(valor), fmt)
        except ValueError as e:
            if "out of range" in str(e) or "must be in" in str(e):
                motivo_calendario = True
            continue
        tiene_hora = any(d in fmt for d in ("%H", "%I", "%M"))
        return dt if tiene_hora else dt.date()
    esperado = " o ".join(formato_legible(f) for f in formatos)
    if motivo_calendario:
        msg = f"'{valor}' no existe en el calendario (formato esperado {esperado})"
    else:
        msg = f"'{valor}' no corresponde al formato {esperado}"
    at.agregar(campo, FECHA_INVALIDA, valor, msg)
    return None


def _hora(at: AtencionComun, valor, formatos: list[str]):
    if valor is None:
        return None
    if isinstance(valor, time):
        return valor
    if isinstance(valor, datetime):
        return valor.time()
    for fmt in formatos:
        try:
            return datetime.strptime(str(valor), fmt).time()
        except ValueError:
            continue
    at.agregar("hora_atencion", FECHA_INVALIDA, valor,
               f"'{valor}' no corresponde al formato de hora "
               f"{' o '.join(formato_legible(f) for f in formatos)}")
    return None


def _cie10(valor, cfg: ConfigFuente):
    if valor is None:
        return None
    c = str(valor).strip().upper()
    if cfg.cie10_quitar_punto:
        c = c.replace(".", "")
    if cfg.cie10_completar_x and re.fullmatch(r"[A-Z][0-9]{2}", c):
        c += "X"       # convención SISPRO para categorías sin subdivisión
    return c or None


def normalizar(at: AtencionComun, cfg: ConfigFuente) -> AtencionComun:
    """Paso 3: unifica formatos. Nunca lanza excepciones por datos malos."""
    v = {campo: None for campo in CAMPOS_MODELO}
    for campo in CAMPOS_MODELO:
        try:
            v[campo] = _texto(at.crudo.get(campo), cfg)
        except Exception as e:
            at.agregar(campo, ERROR_LECTURA, at.crudo.get(campo), f"Valor ilegible: {e}")

    def seguro(campo, funcion):
        try:
            return funcion()
        except Exception as e:  # red de seguridad: se marca y se sigue
            at.agregar(campo, ERROR_LECTURA, at.crudo.get(campo), f"No se pudo normalizar: {e}")
            return None

    fmts = cfg.formatos_fecha
    at.id_atencion = None if v["id_atencion"] is None else str(v["id_atencion"])
    at.numero_documento = None if v["numero_documento"] is None else str(v["numero_documento"])
    at.nombres, at.apellidos, at.nombre_completo = (
        None if v[c] is None else str(v[c]) for c in ("nombres", "apellidos", "nombre_completo"))
    at.tipo_documento = seguro("tipo_documento", lambda: _equivalencia(
        at, "tipo_documento", v["tipo_documento"], cfg, TIPOS_DOCUMENTO_VALIDOS))
    at.sexo = seguro("sexo", lambda: _equivalencia(at, "sexo", v["sexo"], cfg, SEXOS_VALIDOS))
    nac = seguro("fecha_nacimiento", lambda: _fecha(
        at, "fecha_nacimiento", v["fecha_nacimiento"], fmts.get("fecha_nacimiento", [])))
    at.fecha_nacimiento = nac.date() if isinstance(nac, datetime) else nac
    aten = seguro("fecha_atencion", lambda: _fecha(
        at, "fecha_atencion", v["fecha_atencion"], fmts.get("fecha_atencion", [])))
    if "hora_atencion" in cfg.columnas:
        hora = seguro("hora_atencion", lambda: _hora(at, v["hora_atencion"], fmts.get("hora_atencion", [])))
        if hora is not None and aten is not None:
            base = aten.date() if isinstance(aten, datetime) else aten
            aten = datetime.combine(base, hora)
    at.fecha_atencion = aten
    at.codigo_cie10 = seguro("codigo_cie10", lambda: _cie10(v["codigo_cie10"], cfg))
    return at
