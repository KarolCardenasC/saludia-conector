"""Motor FHIR (paso 5): construye el RDA como Bundle de tipo `document`.

Entrada: SOLO una `AtencionComun` válida (nunca una fila de una fuente).
Salida: un Bundle FHIR R4 (dict listo para JSON) con cuatro recursos:
Composition (primer entry), Patient, Encounter y Condition.

Este Bundle es una representación académica del RDA sobre FHIR R4 base.
NO declara ni implementa la guía de implementación del Ministerio de
Salud: no usa perfiles, extensiones ni URIs oficiales.
"""
from __future__ import annotations

import html
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .catalogo import CatalogoCIE10
from .modelo import TIPOS_DOCUMENTO_VALIDOS, AtencionComun

# Espacio de nombres para UUID deterministas (mismo registro → mismos UUID)
NAMESPACE_SALUDIA = uuid.UUID("6f1c2b7e-5a3d-4e8f-9b21-0c4d5e6f7a8b")

LOINC = "http://loinc.org"
SISTEMA_ICD10_OMS = "http://hl7.org/fhir/sid/icd-10"
SISTEMA_CIE10_SISPRO = "urn:saludia:cie10-sispro"          # sistema local del prototipo
SISTEMA_TIPO_DOC = "urn:saludia:tipo-documento"            # sistema local del prototipo
V3_ACTCODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
CONDICION_CATEGORIA = "http://terminology.hl7.org/CodeSystem/condition-category"
GENERO = {"M": "male", "F": "female", "I": "other"}


@dataclass
class ContextoRDA:
    nombre_ips: str
    marca_tiempo: datetime           # momento de la corrida (con zona horaria)
    zona: timezone                   # zona horaria de las fechas de la fuente


def _uuid(at: AtencionComun, recurso: str) -> str:
    return str(uuid.uuid5(NAMESPACE_SALUDIA, f"{at.fuente}|{at.id_atencion}|{recurso}"))


def fecha_hora_fhir(valor, zona: timezone) -> str:
    """dateTime de FHIR: si hay hora, debe llevar segundos y zona horaria."""
    if isinstance(valor, datetime):
        dt = valor if valor.tzinfo else valor.replace(tzinfo=zona)
        return dt.isoformat(timespec="seconds")
    return valor.isoformat()


def icd10_oms(codigo_sispro: str) -> str:
    """J00X → J00 · J459 → J45.9 (formato de la CIE-10 de la OMS)."""
    if len(codigo_sispro) == 4 and codigo_sispro.endswith("X"):
        return codigo_sispro[:3]
    return f"{codigo_sispro[:3]}.{codigo_sispro[3:]}" if len(codigo_sispro) == 4 else codigo_sispro


def zona_desde_texto(texto: str) -> timezone:
    signo = -1 if texto.startswith("-") else 1
    h, m = texto.lstrip("+-").split(":")
    return timezone(signo * timedelta(hours=int(h), minutes=int(m)))


def construir_bundle(at: AtencionComun, catalogo: CatalogoCIE10, ctx: ContextoRDA) -> dict:
    if not isinstance(at, AtencionComun):
        raise TypeError("El motor FHIR solo acepta atenciones del modelo común")
    if not at.valida:
        raise ValueError("Un registro con errores no genera RDA")

    ids = {r: _uuid(at, r) for r in ("Bundle", "Composition", "Patient", "Encounter", "Condition")}
    url = {r: f"urn:uuid:{v}" for r, v in ids.items()}
    fecha_atencion = fecha_hora_fhir(at.fecha_atencion, ctx.zona)
    nombre_dx = catalogo.nombres.get(at.codigo_cie10, "")

    paciente = {
        "resourceType": "Patient",
        "id": ids["Patient"],
        "identifier": [{
            "type": {"coding": [{"system": SISTEMA_TIPO_DOC, "code": at.tipo_documento,
                                 "display": TIPOS_DOCUMENTO_VALIDOS[at.tipo_documento]}]},
            "system": f"urn:saludia:documento:{at.tipo_documento.lower()}",
            "value": at.numero_documento,
        }],
        "gender": GENERO[at.sexo],
        "birthDate": at.fecha_nacimiento.isoformat(),
    }
    if at.nombres or at.apellidos:
        nombre = {}
        if at.apellidos:
            nombre["family"] = at.apellidos
        if at.nombres:
            nombre["given"] = at.nombres.split()
        paciente["name"] = [nombre]
    elif at.nombre_completo:
        paciente["name"] = [{"text": at.nombre_completo}]

    encuentro = {
        "resourceType": "Encounter",
        "id": ids["Encounter"],
        "identifier": [{"system": f"urn:saludia:atencion:{at.fuente}", "value": at.id_atencion}],
        "status": "finished",
        "class": {"system": V3_ACTCODE, "code": "AMB", "display": "ambulatory"},
        "subject": {"reference": url["Patient"]},
        "period": {"start": fecha_atencion},
        "diagnosis": [{"condition": {"reference": url["Condition"]}, "rank": 1}],
        "serviceProvider": {"display": ctx.nombre_ips},
    }

    condicion = {
        "resourceType": "Condition",
        "id": ids["Condition"],
        "category": [{"coding": [{"system": CONDICION_CATEGORIA, "code": "encounter-diagnosis",
                                  "display": "Encounter Diagnosis"}]}],
        "code": {
            "coding": [
                {"system": SISTEMA_ICD10_OMS, "code": icd10_oms(at.codigo_cie10),
                 **({"display": nombre_dx} if nombre_dx else {})},
                {"system": SISTEMA_CIE10_SISPRO, "code": at.codigo_cie10},
            ],
            "text": f"{at.codigo_cie10} {nombre_dx}".strip(),
        },
        "subject": {"reference": url["Patient"]},
        "encounter": {"reference": url["Encounter"]},
    }

    texto_seccion = html.escape(f"Diagnóstico principal: {at.codigo_cie10} {nombre_dx}".strip())
    composicion = {
        "resourceType": "Composition",
        "id": ids["Composition"],
        "status": "final",
        "type": {"coding": [{"system": LOINC, "code": "34133-9",
                             "display": "Summary of episode note"}]},
        "subject": {"reference": url["Patient"]},
        "encounter": {"reference": url["Encounter"]},
        "date": fecha_atencion,
        "author": [{"display": ctx.nombre_ips}],
        "title": "Resumen Digital de Atención (RDA) · prototipo académico, datos sintéticos",
        "section": [{
            "title": "Diagnósticos de la atención",
            "code": {"coding": [{"system": LOINC, "code": "29548-5",
                                 "display": "Diagnosis Narrative"}]},
            "text": {"status": "generated",
                     "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{texto_seccion}</div>'},
            "entry": [{"reference": url["Condition"]}],
        }],
    }

    return {
        "resourceType": "Bundle",
        "id": ids["Bundle"],
        "meta": {"tag": [{"system": "urn:saludia:etiquetas", "code": "sintetico",
                          "display": "Datos sintéticos · prototipo académico"}]},
        "identifier": {"system": "urn:saludia:rda", "value": f"{at.fuente}-{at.id_atencion}"},
        "type": "document",
        "timestamp": ctx.marca_tiempo.isoformat(timespec="seconds"),
        "entry": [
            {"fullUrl": url["Composition"], "resource": composicion},
            {"fullUrl": url["Patient"], "resource": paciente},
            {"fullUrl": url["Encounter"], "resource": encuentro},
            {"fullUrl": url["Condition"], "resource": condicion},
        ],
    }
