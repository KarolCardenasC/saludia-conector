"""Prueba exploratoria con casos difíciles · FUERA DE LOS CRITERIOS C1–C5.

No cambia metas, no entra en metricas.json ni en el dashboard de C1–C5.
Para cada caso, el comportamiento esperado se escribió en
exploratorio/casos_dificiles.csv ANTES de ejecutar (columna "Esperado").
Si el sistema no detecta algo, no se ajusta el código: se reporta como
hallazgo para la sección 6 (aprendizaje).

Clasificación de cada caso:
  ✓ coincide          el sistema hizo lo esperado (aceptar y normalizar, o marcar)
  ✗ no detecta        se esperaba marcar y el sistema lo aceptó (riesgo)
  ◐ marca de más      se esperaba aceptar y el sistema lo marcó (falso positivo práctico)
  ◐ normaliza distinto se aceptó, pero el valor normalizado no es el esperado
"""
from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path

from .catalogo import cargar_catalogo
from .conector import cargar_parametros, procesar_fuente
from .mapeo import cargar_mapeo
from .motor_fhir import ContextoRDA, zona_desde_texto

ETIQUETA = "Hallazgos exploratorios, fuera de los criterios C1–C5"
VARIANTES = {
    "A": ("exploratorio/mapeo_exploratorio_A.yaml", "configuración por defecto (igual que la fuente 2)"),
    "B": ("exploratorio/mapeo_exploratorio_B.yaml", "con las opciones cie10_quitar_punto y cie10_completar_x"),
}
SIMBOLO = {"coincide": "✓", "no detecta": "✗", "marca de más": "◐", "normaliza distinto": "◐"}


def _txt(v) -> str:
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    return "" if v is None else str(v)


def _clasificar(esperado: str, valido: bool, valor_esperado: str, atencion) -> tuple[str, str]:
    if esperado == "marcar":
        return ("coincide", "") if not valido else ("no detecta", "")
    if not valido:
        return "marca de más", ""
    if valor_esperado:
        campo, valor = valor_esperado.split("=", 1)
        obtenido = _txt(getattr(atencion, campo))
        if obtenido != valor:
            return "normaliza distinto", f"{campo}: esperado '{valor}', obtenido '{obtenido}'"
        return "coincide", f"{campo} = {obtenido}"
    return "coincide", ""


def correr_variante(raiz: Path, variante: str) -> dict:
    p = cargar_parametros(raiz)
    ruta_yaml, descripcion = VARIANTES[variante]
    cfg = cargar_mapeo(raiz / ruta_yaml, raiz)
    cat = cargar_catalogo(raiz, p["rutas"]["referencia_cie10_oficial"], p["rutas"]["referencia_cie10_subconjunto"])
    zona = zona_desde_texto(p["ips_simulada"]["zona_horaria"])
    ctx = ContextoRDA(p["ips_simulada"]["nombre"], datetime.now(zona), zona)
    dir_sal = raiz / p["rutas"]["salidas"] / "exploratorio" / variante
    rf = procesar_fuente(cfg, cat, ctx, dir_sal)

    with open(cfg.ruta, encoding="utf-8", newline="") as f:
        doc = list(csv.DictReader(f))
    casos = []
    for i, (fila_doc, rr) in enumerate(zip(doc, rf.registros), start=1):
        at = rr.atencion
        valido = at.valida and bool(rr.validacion and rr.validacion.valido)
        clase, detalle = _clasificar(fila_doc["Esperado"], valido, fila_doc["ValorEsperado"], at)
        casos.append({
            "caso": f"EX-{i:02d}", "fila": at.fila, "nombre": fila_doc["Caso"],
            "descripcion": fila_doc["Descripcion"], "esperado": fila_doc["Esperado"],
            "resultado": "aceptado (RDA válido)" if valido else "marcado con error",
            "hallazgos": [f"{h.tipo_error}: {h.mensaje}" for h in at.hallazgos],
            "detalle": detalle, "clasificacion": clase,
        })
    return {"variante": variante, "descripcion": descripcion, "mapeo": ruta_yaml,
            "casos": casos, "resumen": {k: sum(c["clasificacion"] == k for c in casos) for k in SIMBOLO}}


def correr_exploratorio(raiz: Path) -> dict:
    resultado = {
        "etiqueta": ETIQUETA,
        "nota": ("Prueba de aprendizaje con casos difíciles que NO son errores sembrados. No modifica "
                 "las metas ni los criterios C1–C5 y no se usa para confirmar la hipótesis H2. "
                 "Lo esperado de cada caso se definió antes de ejecutar."),
        "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "variantes": [correr_variante(raiz, v) for v in VARIANTES],
    }
    sal = raiz / cargar_parametros(raiz)["rutas"]["salidas"]
    (sal / "hallazgos_exploratorios.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    (sal / "hallazgos_exploratorios.md").write_text(a_markdown(resultado), encoding="utf-8")
    return resultado


def a_markdown(r: dict) -> str:
    lineas = [f"# {r['etiqueta']}", "", f"> {r['nota']}", "", f"Generado: {r['generado']}", ""]
    for v in r["variantes"]:
        lineas += [f"## Variante {v['variante']} · {v['descripcion']}", "",
                   f"Mapeo: `{v['mapeo']}` · " + " · ".join(f"{SIMBOLO[k]} {k}: {n}" for k, n in v["resumen"].items()),
                   "", "| Caso | Situación | Se esperaba | El sistema | Resultado | Detalle |",
                   "|---|---|---|---|---|---|"]
        for c in v["casos"]:
            det = c["detalle"] or "; ".join(c["hallazgos"]) or "—"
            lineas.append(f"| {c['caso']} | {c['nombre']} | {c['esperado']} | {c['resultado']} | "
                          f"{SIMBOLO[c['clasificacion']]} {c['clasificacion']} | {det.replace('|', '/')} |")
        lineas.append("")
    return "\n".join(lineas)
