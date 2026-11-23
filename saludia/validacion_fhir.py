"""Validación estructural del RDA (paso 6).

"Validación estructural R4 base + reglas de documento":

  A. R4 base: el Bundle se parsea con fhir.resources 6.4.0 (FHIR 4.0.1).
     Esto comprueba tipos de datos, cardinalidades, campos obligatorios,
     formato de fechas y que no haya claves desconocidas.

  B. Reglas de documento (verificación propia). La librería NO comprueba
     invariantes FHIRPath, vínculos a conjuntos de valores, zona horaria
     de los dateTime ni que las referencias se resuelvan. Lo verificamos:
       bdl-7  fullUrl únicos              bdl-9  identifier con system y value
       bdl-10 timestamp presente          bdl-11 Composition como primer entry
       códigos obligatorios dentro de su conjunto de valores R4
       dateTime/instant con zona horaria cuando traen hora
       referencias internas resolubles y del tipo esperado
       Composition.section referencia el Condition

IMPORTANTE: esto NO es validación de conformidad con la guía de
implementación del RDA del Ministerio de Salud (perfiles, extensiones,
terminologías nacionales). Solo garantiza que el documento es FHIR R4
estructuralmente correcto y coherente por dentro.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

import fhir.resources
from fhir.resources.bundle import Bundle

VERSION_FHIR = fhir.resources.__fhir_version__
ALCANCE = "Validación estructural R4 base + reglas de documento (no es conformidad con la guía del Ministerio)"

# Conjuntos de valores R4 (binding "required") de los campos que usamos
VS_BUNDLE_TYPE = {"document", "message", "transaction", "transaction-response", "batch",
                  "batch-response", "history", "searchset", "collection"}
VS_COMPOSITION_STATUS = {"preliminary", "final", "amended", "entered-in-error"}
VS_ENCOUNTER_STATUS = {"planned", "arrived", "triaged", "in-progress", "onleave", "finished",
                       "cancelled", "entered-in-error", "unknown"}
VS_GENDER = {"male", "female", "other", "unknown"}

# Expresiones regulares oficiales de R4 (dateTime e instant)
RE_DATETIME = re.compile(
    r"([0-9]([0-9]([0-9][1-9]|[1-9]0)|[1-9]00)|[1-9]000)(-(0[1-9]|1[0-2])(-(0[1-9]|[1-2][0-9]|3[0-1])"
    r"(T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?(Z|(\+|-)((0[0-9]|1[0-3]):[0-5][0-9]|14:00)))?)?)?")
RE_INSTANT = re.compile(
    r"([0-9]([0-9]([0-9][1-9]|[1-9]0)|[1-9]00)|[1-9]000)-(0[1-9]|1[0-2])-(0[1-9]|[1-2][0-9]|3[0-1])"
    r"T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?(Z|(\+|-)((0[0-9]|1[0-3]):[0-5][0-9]|14:00))")
TIPOS_REQUERIDOS = ("Composition", "Patient", "Encounter", "Condition")


@dataclass
class ResultadoValidacion:
    valido: bool
    errores_r4: list[str] = field(default_factory=list)       # de fhir.resources
    errores_documento: list[str] = field(default_factory=list)  # reglas propias

    @property
    def errores(self) -> list[str]:
        return [f"[R4] {e}" for e in self.errores_r4] + [f"[documento] {e}" for e in self.errores_documento]


def _referencias(nodo, ruta=""):
    """Recorre el recurso y entrega (ruta, valor) de cada Reference.reference."""
    if isinstance(nodo, dict):
        for k, v in nodo.items():
            if k == "reference" and isinstance(v, str):
                yield ruta, v
            else:
                yield from _referencias(v, f"{ruta}.{k}" if ruta else k)
    elif isinstance(nodo, list):
        for i, v in enumerate(nodo):
            yield from _referencias(v, f"{ruta}[{i}]")


def _reglas_documento(b: dict) -> list[str]:
    e: list[str] = []
    if b.get("resourceType") != "Bundle":
        return ["El recurso raíz no es un Bundle"]
    if b.get("type") not in VS_BUNDLE_TYPE:
        e.append(f"Bundle.type '{b.get('type')}' no pertenece al conjunto de valores R4")
    elif b["type"] != "document":
        e.append("Bundle.type debe ser 'document' para un RDA")
    ident = b.get("identifier") or {}
    if not (ident.get("system") and ident.get("value")):
        e.append("bdl-9: un documento debe tener identifier con system y value")
    ts = b.get("timestamp")
    if not ts:
        e.append("bdl-10: un documento debe tener timestamp")
    elif not RE_INSTANT.fullmatch(ts):
        e.append(f"Bundle.timestamp '{ts}' no es un instant válido (requiere segundos y zona horaria)")

    entradas = b.get("entry") or []
    recursos = [x.get("resource") or {} for x in entradas]
    if not recursos or recursos[0].get("resourceType") != "Composition":
        e.append("bdl-11: el primer entry de un documento debe ser una Composition")
    full_urls = [x.get("fullUrl") for x in entradas]
    if len(set(full_urls)) != len(full_urls):
        e.append("bdl-7: hay fullUrl repetidos")
    por_url = {}
    for x in entradas:
        fu = x.get("fullUrl") or ""
        if not fu.startswith("urn:uuid:"):
            e.append(f"fullUrl '{fu}' no tiene la forma urn:uuid:")
        else:
            try:
                uuid.UUID(fu[9:])
            except ValueError:
                e.append(f"fullUrl '{fu}' no contiene un UUID válido")
        por_url[fu] = (x.get("resource") or {}).get("resourceType")

    tipos = [r.get("resourceType") for r in recursos]
    for t in TIPOS_REQUERIDOS:
        if tipos.count(t) != 1:
            e.append(f"El RDA debe tener exactamente un {t} (tiene {tipos.count(t)})")

    for r in recursos:
        tipo = r.get("resourceType")
        for ruta, ref in _referencias(r):
            if ref not in por_url:
                e.append(f"{tipo}.{ruta}: la referencia '{ref}' no se resuelve dentro del Bundle")
        if tipo == "Composition":
            if r.get("status") not in VS_COMPOSITION_STATUS:
                e.append(f"Composition.status '{r.get('status')}' fuera del conjunto de valores R4")
            codigos = [(c.get("system"), c.get("code")) for c in (r.get("type") or {}).get("coding", [])]
            if ("http://loinc.org", "34133-9") not in codigos:
                e.append("Composition.type debe incluir LOINC 34133-9")
            if por_url.get((r.get("subject") or {}).get("reference")) != "Patient":
                e.append("Composition.subject debe referenciar al Patient")
            if por_url.get((r.get("encounter") or {}).get("reference")) != "Encounter":
                e.append("Composition.encounter debe referenciar al Encounter")
            refs_seccion = [en.get("reference") for s in r.get("section", []) for en in s.get("entry", [])]
            if "Condition" not in [por_url.get(x) for x in refs_seccion]:
                e.append("Composition.section debe referenciar el Condition")
            if r.get("date") and not RE_DATETIME.fullmatch(r["date"]):
                e.append(f"Composition.date '{r['date']}' no es un dateTime R4 (¿falta la zona horaria?)")
            for s in r.get("section", []):
                div = (s.get("text") or {}).get("div", "")
                if div and 'xmlns="http://www.w3.org/1999/xhtml"' not in div:
                    e.append("La narrativa de la sección debe ser XHTML con xmlns")
        elif tipo == "Patient":
            if r.get("gender") not in VS_GENDER:
                e.append(f"Patient.gender '{r.get('gender')}' fuera del conjunto de valores R4")
        elif tipo == "Encounter":
            if r.get("status") not in VS_ENCOUNTER_STATUS:
                e.append(f"Encounter.status '{r.get('status')}' fuera del conjunto de valores R4")
            inicio = (r.get("period") or {}).get("start")
            if inicio and not RE_DATETIME.fullmatch(inicio):
                e.append(f"Encounter.period.start '{inicio}' no es un dateTime R4 (¿falta la zona horaria?)")
            if por_url.get((r.get("subject") or {}).get("reference")) != "Patient":
                e.append("Encounter.subject debe referenciar al Patient")
        elif tipo == "Condition":
            sistemas = {c.get("system") for c in (r.get("code") or {}).get("coding", [])}
            if "http://hl7.org/fhir/sid/icd-10" not in sistemas:
                e.append("Condition.code debe usar el sistema CIE-10 (http://hl7.org/fhir/sid/icd-10)")
            if por_url.get((r.get("subject") or {}).get("reference")) != "Patient":
                e.append("Condition.subject debe referenciar al Patient")
    return e


def validar_bundle(bundle: dict) -> ResultadoValidacion:
    errores_r4: list[str] = []
    try:
        Bundle.parse_obj(bundle)
    except Exception as ex:  # pydantic.ValidationError u otros
        lineas = [l.strip() for l in str(ex).splitlines() if l.strip()]
        errores_r4 = lineas[1:] if len(lineas) > 1 else lineas
    try:
        errores_doc = _reglas_documento(bundle)
    except Exception as ex:  # nunca detener la corrida por un Bundle raro
        errores_doc = [f"No se pudo revisar el documento: {ex}"]
    return ResultadoValidacion(not errores_r4 and not errores_doc, errores_r4, errores_doc)
