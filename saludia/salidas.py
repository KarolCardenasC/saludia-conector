"""Escritura de salidas (paso 7): reporte de errores, ejemplo de RDA y resumen."""
from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path

from .conector import ResultadoCorrida
from .validacion_fhir import ALCANCE

CAMPOS_REPORTE = ["id_atencion", "fuente", "fila", "campo", "tipo_error", "valor_encontrado", "mensaje"]


def _texto(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def filas_reporte(corrida: ResultadoCorrida) -> list[dict]:
    filas = []
    for f in corrida.fuentes:
        if not f.conectada:
            filas.append({"id_atencion": "", "fuente": f.id, "fila": "", "campo": "(fuente)",
                          "tipo_error": "fuente_no_conectada", "valor_encontrado": f.archivo_mapeo,
                          "mensaje": f.error_configuracion or ""})
            continue
        for rr in f.registros:
            at = rr.atencion
            for h in at.hallazgos:
                filas.append({"id_atencion": at.id_atencion or "", "fuente": at.fuente, "fila": at.fila,
                              "campo": h.campo, "tipo_error": h.tipo_error,
                              "valor_encontrado": _texto(h.valor_encontrado), "mensaje": h.mensaje})
            if rr.validacion is not None and not rr.validacion.valido:
                for e in rr.validacion.errores:
                    filas.append({"id_atencion": at.id_atencion or "", "fuente": at.fuente, "fila": at.fila,
                                  "campo": "(RDA)", "tipo_error": "bundle_invalido",
                                  "valor_encontrado": "", "mensaje": e})
    return filas


def escribir_reporte_errores(corrida: ResultadoCorrida, carpeta: Path) -> tuple[Path, Path]:
    filas = filas_reporte(corrida)
    ruta_csv, ruta_json = carpeta / "reporte_errores.csv", carpeta / "reporte_errores.json"
    with open(ruta_csv, "w", encoding="utf-8-sig", newline="") as f:   # BOM: Excel abre bien las tildes
        w = csv.DictWriter(f, fieldnames=CAMPOS_REPORTE)
        w.writeheader()
        w.writerows(filas)
    ruta_json.write_text(json.dumps({
        "generado": corrida.inicio.isoformat(timespec="seconds"),
        "total_hallazgos": len(filas),
        "registros_con_error": len({(r["fuente"], r["fila"]) for r in filas if r["fila"] != ""}),
        "nota": "Los registros con error se reportan; no se borran ni se corrigen y no generan RDA.",
        "hallazgos": filas,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta_csv, ruta_json


def escribir_ejemplo_rda(corrida: ResultadoCorrida, carpeta: Path) -> Path | None:
    for rr in corrida.registros():
        if rr.validacion is not None and rr.validacion.valido:
            ruta = carpeta / "ejemplo_rda.json"
            ruta.write_text(json.dumps(rr.bundle, ensure_ascii=False, indent=2), encoding="utf-8")
            return ruta
    return None


def resumen_corrida(corrida: ResultadoCorrida) -> dict:
    fuentes = []
    for f in corrida.fuentes:
        regs = f.registros
        fuentes.append({
            "id": f.id, "nombre": f.nombre, "tipo": f.tipo, "archivo_mapeo": f.archivo_mapeo,
            "archivo_fuente": f.archivo_fuente, "conectada": f.conectada,
            "error_configuracion": f.error_configuracion,
            "registros_extraidos": len(regs),
            "registros_validos": sum(r.atencion.valida for r in regs),
            "registros_con_error": sum(not r.atencion.valida for r in regs),
            "bundles_generados": sum(r.bundle is not None for r in regs),
            "bundles_validos": sum(bool(r.validacion and r.validacion.valido) for r in regs),
            "columnas_ignoradas": f.lectura.columnas_ignoradas if f.lectura else [],
            "segundos_lectura": round(f.segundos_lectura, 6),
            "sha256_antes": f.huella_antes, "sha256_despues": f.huella_despues,
            "fuente_intacta": f.intacta,
            "tiempos_por_registro_s": [round(r.segundos, 6) for r in regs],
        })
    return {
        "inicio": corrida.inicio.isoformat(timespec="seconds"),
        "version_fhir": corrida.version_fhir,
        "alcance_validacion": ALCANCE,
        "catalogo_cie10": {"origen": corrida.catalogo_origen, "codigos": corrida.catalogo_codigos},
        "segundos_total_corrida": round(corrida.segundos_total, 4),
        "fuentes": fuentes,
    }


def escribir_resumen(corrida: ResultadoCorrida, carpeta: Path) -> Path:
    ruta = carpeta / "corrida.json"
    ruta.write_text(json.dumps(resumen_corrida(corrida), ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta
