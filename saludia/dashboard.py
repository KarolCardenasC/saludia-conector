"""Dashboard HTML autocontenido (CSS, JS y SVG inline; sin CDN ni internet).

Se genera con plantillas de texto de Python a partir de los resultados
REALES de la corrida (ResultadoCorrida + metricas.json). No inventa ni
rellena ningún valor: si C5 no se ha ejecutado, muestra "pendiente".
"""
from __future__ import annotations

import html
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from . import LEYENDA
from .conector import ResultadoCorrida
from .modelo import CAMPOS_OBLIGATORIOS
from .salidas import filas_reporte

TITULAR = "Tus atenciones, rumbo a la IHCE, sin cambiar de software"
SUBTITULO = ("SALUDIA lee los registros que tu IPS ya tiene, los ordena en un modelo común y los "
             "convierte en Resúmenes Digitales de Atención en HL7 FHIR. Este tablero muestra una "
             "corrida real del prototipo con datos sintéticos.")
EQUIPO = ["Julián David Avendaño Valderrama", "Karol Vanessa Cardenas Chavarrio",
          "Erika Yuliana Gómez Rodríguez", "Nasly Natalia Valencia Palacios"]
INSTITUCION = "Universidad El Bosque · Gestión de Tecnología e Innovación"

# Colores de serie por fuente (validados con el validador de paletas: claro/oscuro)
SERIES = ["var(--serie-1)", "var(--serie-2)", "var(--serie-3)", "var(--serie-1)"]

NOMBRE_ERROR = {
    "campo_obligatorio_vacio": "Campo obligatorio vacío", "fecha_invalida": "Fecha inválida",
    "cie10_inexistente": "CIE-10 inexistente", "valor_no_reconocido": "Valor no reconocido",
    "fecha_incoherente": "Fecha incoherente", "id_duplicado": "Id duplicado",
    "error_lectura": "Error de lectura", "cie10_no_habilitado": "CIE-10 no habilitado",
    "bundle_invalido": "RDA inválido", "fuente_no_conectada": "Fuente no conectada",
}
TIPO_FUENTE = {"sqlite": "SQLite", "csv": "CSV", "excel": "Excel"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

e = html.escape


# ---------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------
def num(x: float, dec: int = 0) -> str:
    """Formato es-CO: punto de miles, coma decimal."""
    s = f"{x:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def fecha_larga(dt: datetime) -> str:
    return f"{dt.day} de {MESES[dt.month - 1]} de {dt.year}, {dt:%H:%M}"


def nombre_corto(fuente) -> str:
    m = re.match(r"fuente(\d+)", fuente.id)
    tipo = TIPO_FUENTE.get(fuente.tipo, fuente.tipo)
    return f"Fuente {m.group(1)} · {tipo}" if m else f"{fuente.nombre} · {tipo}"


def valor_txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def resaltar_json(texto: str) -> str:
    patron = re.compile(r'("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)')
    salida, pos = [], 0
    for m in patron.finditer(texto):
        salida.append(e(texto[pos:m.start()]))
        if m.group(1):
            clase = "k" if m.group(2) else "s"
            salida.append(f'<span class="j{clase}">{e(m.group(1))}</span>{e(m.group(2) or "")}')
        elif m.group(3):
            salida.append(f'<span class="jb">{m.group(3)}</span>')
        else:
            salida.append(f'<span class="jn">{m.group(4)}</span>')
        pos = m.end()
    salida.append(e(texto[pos:]))
    return "".join(salida)


def paso_bonito(maximo: float, partes: int) -> float:
    crudo = maximo / partes if maximo > 0 else 1
    base = 10 ** math.floor(math.log10(crudo))
    for f in (1, 2, 2.5, 5, 10):
        if f * base >= crudo:
            return f * base
    return 10 * base


# ---------------------------------------------------------------------
# Piezas SVG
# ---------------------------------------------------------------------
LOGO = """<svg class="logo" viewBox="0 0 48 48" role="img" aria-label="Logo de SALUDIA">
<defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2a78d6"/>
<stop offset="1" stop-color="#1baf7a"/></linearGradient></defs>
<rect width="48" height="48" rx="13" fill="url(#lg)"/>
<path d="M16 10.5h12.5l7 7V36a2.5 2.5 0 0 1-2.5 2.5H16A2.5 2.5 0 0 1 13.5 36V13A2.5 2.5 0 0 1 16 10.5z"
 fill="none" stroke="#fff" stroke-width="2.4" stroke-linejoin="round"/>
<path d="M28.5 10.5v7h7" fill="none" stroke="#fff" stroke-width="2.4" stroke-linejoin="round"/>
<path d="M17.5 28h3.5l2.4-4.6 3.6 8.2 2.3-3.6h3.2" fill="none" stroke="#fff" stroke-width="2.4"
 stroke-linecap="round" stroke-linejoin="round"/></svg>"""


def _barra_h(x: float, y: float, w: float, h: float, redondo: bool) -> str:
    """Barra horizontal con el extremo de datos redondeado (4 px) y base recta."""
    if w <= 0:
        return ""
    r = min(4, w / 2, h / 2) if redondo else 0
    return (f"M{x:.1f},{y:.1f}h{w - r:.1f}a{r},{r} 0 0 1 {r},{r}v{h - 2 * r:.1f}"
            f"a{r},{r} 0 0 1 -{r},{r}h-{w - r:.1f}z")


def _columna(x: float, base: float, w: float, h: float) -> str:
    if h <= 0:
        return ""
    r = min(4, w / 2, h)
    return (f"M{x:.1f},{base:.1f}v-{h - r:.1f}a{r},{r} 0 0 1 {r},-{r}h{w - 2 * r:.1f}"
            f"a{r},{r} 0 0 1 {r},{r}v{h - r:.1f}z")


def anillo(fraccion: float | None, clase: str, pendiente: bool = False) -> str:
    r, cx = 34, 42
    circ = 2 * math.pi * r
    frac = 0 if fraccion is None else max(0.0, min(1.0, fraccion))
    trazo = f'stroke-dasharray="{circ * frac:.2f} {circ:.2f}"'
    extra = ' stroke-dasharray="4 6"' if pendiente else ""
    return (f'<svg class="anillo {clase}" viewBox="0 0 84 84" aria-hidden="true">'
            f'<circle cx="{cx}" cy="{cx}" r="{r}" class="pista"{extra}/>'
            + ("" if pendiente else
               f'<circle cx="{cx}" cy="{cx}" r="{r}" class="arco" {trazo} transform="rotate(-90 {cx} {cx})"/>')
            + "</svg>")


def grafico_fuentes(fuentes: list[dict]) -> str:
    ancho, izq, fila, grosor = 560, 128, 46, 22
    escala = (ancho - izq - 150) / max([f["extraidos"] for f in fuentes] + [1])
    alto = 18 + fila * len(fuentes)
    partes = [f'<svg viewBox="0 0 {ancho} {alto}" class="grafico" role="img" '
              f'aria-labelledby="g1t"><title id="g1t">Atenciones por fuente: RDA válidos y con error</title>']
    for i, f in enumerate(fuentes):
        y = 10 + i * fila
        wv, we = f["validos"] * escala, f["errores"] * escala
        partes.append(f'<text x="{izq - 12}" y="{y + grosor / 2 + 4}" class="eje-txt" text-anchor="end">{e(f["corto"])}</text>')
        tip = e(f'{f["corto"]}: {f["extraidos"]} extraídas · {f["validos"]} con RDA válido · {f["errores"]} con error')
        partes.append(f'<path d="{_barra_h(izq, y, wv, grosor, f["errores"] == 0)}" style="fill:{f["color"]}" data-tip="{tip}"/>')
        if f["errores"]:
            partes.append(f'<path d="{_barra_h(izq + wv + 2, y, max(we - 2, 1), grosor, True)}" '
                          f'class="m-error" data-tip="{tip}"/>')
        partes.append(f'<text x="{izq + wv + we + 10}" y="{y + grosor / 2 + 4}" class="valor-txt">'
                      f'{f["validos"]} válidas · {f["errores"]} con error</text>')
    partes.append(f'<line x1="{izq}" x2="{izq}" y1="4" y2="{alto - 4}" class="base"/></svg>')
    return "".join(partes)


def grafico_errores(conteo: list[tuple[str, int, dict]]) -> str:
    if not conteo:
        return '<p class="vacio">No se encontraron errores en esta corrida.</p>'
    ancho, izq, fila, grosor = 560, 170, 38, 20
    maximo = max(c for _, c, _ in conteo)
    escala = (ancho - izq - 60) / maximo
    alto = 14 + fila * len(conteo)
    partes = [f'<svg viewBox="0 0 {ancho} {alto}" class="grafico" role="img" aria-labelledby="g2t">'
              f'<title id="g2t">Errores reportados por tipo</title>']
    for i, (tipo, cant, por_fuente) in enumerate(conteo):
        y = 8 + i * fila
        w = cant * escala
        detalle = " · ".join(f"{k}: {v}" for k, v in por_fuente.items())
        partes.append(f'<text x="{izq - 12}" y="{y + grosor / 2 + 4}" class="eje-txt" text-anchor="end">{e(NOMBRE_ERROR.get(tipo, tipo))}</text>')
        partes.append(f'<path d="{_barra_h(izq, y, w, grosor, True)}" class="m-error" '
                      f'data-tip="{e(NOMBRE_ERROR.get(tipo, tipo))}: {cant} ({e(detalle)})"/>')
        partes.append(f'<text x="{izq + w + 8}" y="{y + grosor / 2 + 4}" class="valor-txt">{cant}</text>')
    partes.append(f'<line x1="{izq}" x2="{izq}" y1="2" y2="{alto - 2}" class="base"/></svg>')
    return "".join(partes)


def grafico_tiempos(tiempos_ms: list[float]) -> tuple[str, dict]:
    if not tiempos_ms:
        return '<p class="vacio">Sin tiempos.</p>', {}
    ordenados = sorted(tiempos_ms)
    p98 = ordenados[min(len(ordenados) - 1, int(0.98 * len(ordenados)))]
    paso = paso_bonito(p98, 14)
    nbins = max(1, math.ceil(p98 / paso))
    limite = nbins * paso
    conteos = [0] * (nbins + 1)                    # última barra: por encima del límite
    for t in tiempos_ms:
        conteos[min(int(t // paso), nbins) if t < limite else nbins] += 1
    if conteos[-1] == 0:
        conteos.pop()
    ancho, alto, izq, abajo, arriba = 1100, 250, 44, 38, 30
    plot_w = ancho - izq - 12
    plot_h = alto - abajo - arriba
    n = len(conteos)
    banda = plot_w / n
    col_w = min(24, banda - 2)
    ymax = max(conteos)
    paso_y = paso_bonito(ymax, 4)
    techo = math.ceil(ymax / paso_y) * paso_y
    base = alto - abajo
    partes = [f'<svg viewBox="0 0 {ancho} {alto}" class="grafico" role="img" aria-labelledby="g3t">'
              f'<title id="g3t">Distribución del tiempo por atención en milisegundos</title>']
    v = 0
    while v <= techo + 1e-9:
        y = base - plot_h * v / techo
        partes.append(f'<line x1="{izq}" x2="{ancho - 12}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                      f'<text x="{izq - 8}" y="{y + 4:.1f}" class="eje-txt" text-anchor="end">{num(v)}</text>')
        v += paso_y
    for i, c in enumerate(conteos):
        x = izq + i * banda + (banda - col_w) / 2
        h = plot_h * c / techo
        desde, hasta = i * paso, (i + 1) * paso
        rango = (f"≥ {num(limite, 1)} ms" if i == nbins else f"{num(desde, 1)}–{num(hasta, 1)} ms")
        partes.append(f'<path d="{_columna(x, base, col_w, h)}" class="m-tiempo" '
                      f'data-tip="{e(rango)}: {c} atenciones"/>')
        if c and h < 3:
            partes.append(f'<rect x="{x:.1f}" y="{base - 2}" width="{col_w:.1f}" height="2" class="m-tiempo"/>')
    cada = max(1, n // 5)
    for i in range(0, n + 1, cada):
        x = izq + i * banda
        etiqueta = num(i * paso, 1 if paso < 1 else 0)
        partes.append(f'<text x="{x:.1f}" y="{base + 16}" class="eje-txt" text-anchor="middle">{etiqueta}</text>')
    partes.append(f'<text x="{izq + plot_w / 2}" y="{alto - 4}" class="eje-txt" text-anchor="middle">milisegundos por atención</text>')
    prom, med = statistics.mean(tiempos_ms), statistics.median(tiempos_ms)
    xs = {}
    for valor, nombre in ((med, "mediana"), (prom, "promedio")):
        if valor <= limite:
            xs[nombre] = (izq + plot_w * min(valor / (n * paso), 1), valor)
    for nombre, (x, valor) in xs.items():
        izquierda = nombre == "mediana" and "promedio" in xs and xs["promedio"][0] >= x
        ancla, dx = ("end", -6) if izquierda else ("start", 6)
        partes.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{arriba - 12}" y2="{base}" class="ref"/>'
                      f'<text x="{x + dx:.1f}" y="{arriba - 2}" class="ref-txt" text-anchor="{ancla}">'
                      f'{nombre} {num(valor, 2)} ms</text>')
    partes.append(f'<line x1="{izq}" x2="{ancho - 12}" y1="{base}" y2="{base}" class="base"/></svg>')
    info = {"paso": paso, "limite": limite, "fuera": sum(1 for t in tiempos_ms if t >= limite),
            "maximo": max(tiempos_ms), "promedio": prom, "mediana": med,
            "tabla": [((f"≥ {num(limite, 1)}" if i == nbins else f"{num(i * paso, 1)}–{num((i + 1) * paso, 1)}"), c)
                      for i, c in enumerate(conteos)]}
    return "".join(partes), info


# ---------------------------------------------------------------------
# Datos para el tablero
# ---------------------------------------------------------------------
def _datos_fuentes(corrida: ResultadoCorrida, raiz: Path) -> list[dict]:
    salida = []
    for i, f in enumerate(corrida.fuentes):
        regs = f.registros
        d = {"id": f.id, "nombre": f.nombre, "tipo": f.tipo, "corto": nombre_corto(f),
             "color": SERIES[min(i, len(SERIES) - 1)], "conectada": f.conectada,
             "error_config": f.error_configuracion, "archivo": f.archivo_fuente,
             "archivo_mapeo": f.archivo_mapeo, "extraidos": len(regs),
             "validos": sum(1 for r in regs if r.validacion and r.validacion.valido),
             "errores": sum(1 for r in regs if not r.atencion.valida),
             "intacta": f.intacta, "sha_antes": f.huella_antes, "sha_despues": f.huella_despues,
             "ignoradas": f.lectura.columnas_ignoradas if f.lectura else [],
             "columnas": f.lectura.columnas_usadas if f.lectura else {}, "muestra": [], "yaml": ""}
        ruta_yaml = raiz / "mapeos" / f.archivo_mapeo
        if ruta_yaml.exists():
            d["yaml"] = ruta_yaml.read_text(encoding="utf-8")
        validos = [r for r in regs if r.atencion.valida][:3]
        invalido = next((r for r in regs if not r.atencion.valida), None)
        for r in validos + ([invalido] if invalido else []):
            d["muestra"].append(r.atencion)
        salida.append(d)
    return salida


# ---------------------------------------------------------------------
# Secciones HTML
# ---------------------------------------------------------------------
def _insignia(cumplio: bool | None) -> str:
    if cumplio is True:
        return '<span class="insignia ok">✓ Cumplió</span>'
    if cumplio is False:
        return '<span class="insignia mal">✗ No cumplió</span>'
    return '<span class="insignia pend">… Pendiente</span>'


def _kpis(met: dict) -> str:
    cr = met["criterios"]
    tarjetas = []
    for k in ("C1", "C2", "C3", "C4", "C5"):
        c = cr[k]
        d = c.get("detalle") or {}
        clase = {True: "ok", False: "mal", None: "pend"}[c["cumplio"]]
        if k in ("C1", "C2", "C3"):
            r = c["resultado"]
            frac = None if r is None else r / 100
            centro = (f'<span class="contador" data-valor="{r}" data-dec="1">{num(r, 1)}</span><small>%</small>'
                      if r is not None else "—")
            meta = "= 100 %" if k == "C3" else f"≥ {num(c['meta'])} %"
            if k == "C1":
                linea = f"{d['extraidos']} de {d['en_fuentes_conteo_independiente']} registros extraídos"
            elif k == "C2":
                linea = f"{d['bundles_validos_sin_error_sembrado']} de {d['registros_sin_error_sembrado']} RDA válidos"
            else:
                linea = (f"{d['detectados']} de {d['sembrados']} errores sembrados · "
                         f"{d['falsos_positivos']} falsos positivos")
            anillo_svg = anillo(frac, clase)
        elif k == "C4":
            r = c["resultado"]
            ms = r * 1000 if r is not None else None
            frac = None if r is None else 1 - min(r / c["meta"], 1)
            centro = (f'<span class="contador" data-valor="{ms:.4f}" data-dec="2">{num(ms, 2)}</span><small>ms</small>'
                      if ms is not None else "—")
            meta = f"≤ {num(c['meta'])} s por atención"
            linea = (f"mediana {num(d['mediana_s'] * 1000, 2)} ms · máx. {num(d['maximo_s'] * 1000, 1)} ms · "
                     f"anillo = margen frente a la meta")
            anillo_svg = anillo(frac, clase)
        else:
            res = c["resultado"]
            pendiente = res == "pendiente"
            meta = "sí, solo con un YAML"
            if pendiente:
                centro = '<span class="txt-centro">—</span>'
                linea = "Se mide con el cronómetro de C5"
                anillo_svg = anillo(None, "pend", pendiente=True)
            else:
                frac = {"si": 1.0, "parcial": 0.5, "no": 0.08}.get(res, 0)
                centro = f'<span class="txt-centro">{e({"si": "Sí", "parcial": "Parcial", "no": "No"}.get(res, res))}</span>'
                linea = f"{num(d.get('minutos', 0), 1)} min · {d.get('intentos', 0)} intento(s)"
                anillo_svg = anillo(frac, clase)
        tarjetas.append(f"""
<article class="kpi {clase}">
  <header><span class="kpi-id">{k}</span><h3>{e(c['nombre'])}</h3></header>
  <div class="kpi-cuerpo"><div class="anillo-wrap">{anillo_svg}<div class="centro"><span>{centro}</span></div></div>
  <dl><dt>Meta</dt><dd>{e(meta)}</dd></dl></div>
  <p class="kpi-linea">{e(linea)}</p>
  {_insignia(c['cumplio'])}
</article>""")
    return "".join(tarjetas)


def _stepper(fuentes: list[dict], met: dict, n_errores: int) -> str:
    total = sum(f["extraidos"] for f in fuentes)
    validos = sum(f["validos"] for f in fuentes)
    invalidos = sum(f["errores"] for f in fuentes)
    pasos = [
        ("1", "Adaptadores de lectura", f"{total} registros · solo lectura"),
        ("2", "Archivos de mapeo (YAML)", f"{len(fuentes)} fuentes, sin código nuevo"),
        ("·", "Modelo común de atención", f"{total} atenciones"),
        ("3", "Normalizador", "fechas, sexo y documento unificados"),
        ("4", "Validador de datos (CIE-10)", f"{total - invalidos} válidas · {invalidos} reportadas"),
        ("5", "Motor FHIR · Bundle RDA", f"{validos} documentos"),
        ("6", "Validador FHIR R4", f"{validos} de {total - invalidos} válidos"),
        ("7", "RDA JSON + reporte y métricas", f"{validos} JSON · {n_errores} hallazgos · C1–C5"),
    ]
    items = "".join(f'<li><span class="nodo{" sin-num" if n == "·" else ""}">{n}</span>'
                    f'<strong>{e(t)}</strong><span>{e(s)}</span></li>' for n, t, s in pasos)
    return f'<ol class="stepper">{items}</ol>'


def _pestanas(fuentes: list[dict]) -> str:
    botones, paneles = [], []
    for i, f in enumerate(fuentes):
        sel = "true" if i == 0 else "false"
        botones.append(f'<button role="tab" id="tab-{i}" aria-controls="panel-{i}" aria-selected="{sel}" '
                       f'tabindex="{0 if i == 0 else -1}"><span class="punto" style="background:{f["color"]}"></span>'
                       f'{e(f["corto"])}</button>')
        if not f["conectada"]:
            cuerpo = f'<p class="alerta mal">No se pudo conectar: {e(f["error_config"] or "")}</p>'
        else:
            cols = [(campo, col) for campo, col in f["columnas"].items()]
            enc_crudo = "".join(f"<th><code>{e(col)}</code></th>" for _, col in cols)
            enc_norm = "".join(f"<th>{e(c)}</th>" for c in CAMPOS_OBLIGATORIOS)
            filas_crudo, filas_norm = [], []
            for at in f["muestra"]:
                malos = {h.campo for h in at.hallazgos}
                clase = ' class="fila-error"' if not at.valida else ""
                marca_error = ' class="celda-error"'
                celdas = "".join(
                    f'<td{marca_error if campo in malos else ""}>'
                    f'{e(valor_txt(at.crudo.get(campo))) or "<em>(vacío)</em>"}</td>' for campo, _ in cols)
                filas_crudo.append(f"<tr{clase}><th scope=row>{at.fila}</th>{celdas}</tr>")
                if at.valida:
                    celdas_n = "".join(f"<td>{e(valor_txt(getattr(at, c)))}</td>" for c in CAMPOS_OBLIGATORIOS)
                else:
                    msg = "; ".join(h.mensaje for h in at.hallazgos)
                    celdas_n = (f'<td colspan="{len(CAMPOS_OBLIGATORIOS)}" class="celda-error">'
                                f'Reportado, sin RDA: {e(msg)}</td>')
                filas_norm.append(f"<tr{clase}><th scope=row>{at.fila}</th>{celdas_n}</tr>")
            ign = ", ".join(f"<code>{e(c)}</code>" for c in f["ignoradas"]) or "ninguna"
            cuerpo = f"""
<div class="lado-a-lado">
  <div><h4>Así llega <span class="sub">({e(f['archivo'])})</span></h4>
    <div class="tabla-scroll"><table class="tabla-mini"><thead><tr><th>Fila</th>{enc_crudo}</tr></thead>
    <tbody>{''.join(filas_crudo)}</tbody></table></div>
    <p class="nota">Columnas ignoradas por el mapeo: {ign}</p></div>
  <p class="flecha" aria-hidden="true">↓ mapeo YAML + normalización + validación ↓</p>
  <div><h4>Así queda en el modelo común</h4>
    <div class="tabla-scroll"><table class="tabla-mini"><thead><tr><th>Fila</th>{enc_norm}</tr></thead>
    <tbody>{''.join(filas_norm)}</tbody></table></div></div>
</div>
<details class="yaml"><summary>Ver el archivo de mapeo <code>{e(f['archivo_mapeo'])}</code></summary>
<pre class="codigo">{e(f['yaml'])}</pre></details>"""
        paneles.append(f'<div role="tabpanel" id="panel-{i}" aria-labelledby="tab-{i}"'
                       f'{"" if i == 0 else " hidden"}><h3 class="solo-print">{e(f["corto"])}</h3>{cuerpo}</div>')
    return (f'<div class="pestanas"><div role="tablist" aria-label="Fuentes">{"".join(botones)}</div>'
            f'{"".join(paneles)}</div>')


def _tabla_errores(filas: list[dict], fuentes: list[dict]) -> str:
    nombres = {f["id"]: f["corto"] for f in fuentes}
    tipos = sorted({r["tipo_error"] for r in filas})
    op_fuente = "".join(f'<option value="{e(i)}">{e(n)}</option>' for i, n in nombres.items())
    op_tipo = "".join(f'<option value="{e(t)}">{e(NOMBRE_ERROR.get(t, t))}</option>' for t in tipos)
    cuerpo = "".join(
        f'<tr data-fuente="{e(r["fuente"])}" data-tipo="{e(r["tipo_error"])}">'
        f'<td>{e(nombres.get(r["fuente"], r["fuente"]))}</td><td class="num">{e(str(r["fila"]))}</td>'
        f'<td><code>{e(str(r["id_atencion"])) or "—"}</code></td><td><code>{e(r["campo"])}</code></td>'
        f'<td><span class="chip-error">{e(NOMBRE_ERROR.get(r["tipo_error"], r["tipo_error"]))}</span></td>'
        f'<td><code>{e(r["valor_encontrado"]) or "<em>(vacío)</em>"}</code></td><td>{e(r["mensaje"])}</td></tr>'
        for r in filas)
    return f"""
<div class="filtros no-print">
  <label>Fuente <select id="f-fuente"><option value="">Todas</option>{op_fuente}</select></label>
  <label>Tipo de error <select id="f-tipo"><option value="">Todos</option>{op_tipo}</select></label>
  <label class="buscar">Buscar <input id="f-texto" type="search" placeholder="id, campo, valor o mensaje"></label>
  <span id="f-cuenta" class="cuenta" aria-live="polite">{len(filas)} de {len(filas)}</span>
</div>
<div class="tabla-scroll alto"><table class="tabla-errores"><caption class="sr">Reporte de errores</caption>
<thead><tr><th>Fuente</th><th>Fila</th><th>Atención</th><th>Campo</th><th>Tipo</th><th>Valor encontrado</th><th>Mensaje</th></tr></thead>
<tbody id="errores-cuerpo">{cuerpo}</tbody></table></div>"""


def _seccion_c5(met: dict) -> str:
    c = met["criterios"]["C5"]
    d = c.get("detalle") or {}
    if c["resultado"] == "pendiente":
        return """
<div class="c5 pend">
  <div class="c5-estado"><span class="insignia pend">… Pendiente</span>
  <p>El experimento de C5 todavía no se ha ejecutado. Este valor <strong>no se simula ni se rellena</strong>:
  aparecerá aquí cuando el equipo conecte la fuente 4 escribiendo solo un archivo YAML.</p></div>
  <ol class="c5-pasos">
    <li><code>python scripts/c5_cronometro.py congelar</code><span>huella SHA-256 del código y la configuración</span></li>
    <li><code>python scripts/c5_cronometro.py inicio</code><span>arranca el cronómetro</span></li>
    <li><code>python scripts/c5_cronometro.py intento</code><span>prueba el YAML (las veces necesarias)</span></li>
    <li><code>python scripts/c5_cronometro.py fin</code><span>verifica y da el veredicto: sí, parcial o no</span></li>
  </ol>
</div>"""
    ver = d.get("verificaciones", {})
    nombres = {"codigo_y_config_sin_cambios": "Código y configuración sin cambios",
               "fuente_conectada": "Fuente conectada", "todas_las_filas": "Se procesaron todas las filas",
               "bundles_validos": "RDA estructuralmente válidos",
               "coincide_esperado": "Lo normalizado coincide con el resultado esperado"}
    checks = "".join(f'<li class="{"ok" if v else "mal"}">{"✓" if v else "✗"} {e(nombres.get(k, k))}</li>'
                     for k, v in ver.items())
    motivos = "".join(f"<li>{e(m)}</li>" for m in d.get("motivos", []))
    mapeo = d.get("mapeo") or {}
    comp = d.get("comparacion_esperado") or {}
    clase = {True: "ok", False: "mal", None: "pend"}[c["cumplio"]]
    return f"""
<div class="c5 {clase}">
  <div class="c5-cifras">
    <div><span class="grande">{e({'si': 'Sí', 'parcial': 'Parcial', 'no': 'No'}.get(c['resultado'], str(c['resultado'])))}</span><span>veredicto</span></div>
    <div><span class="grande">{num(d.get('minutos', 0), 1)}</span><span>minutos (reloj del sistema)</span></div>
    <div><span class="grande">{d.get('intentos', 0)}</span><span>intentos</span></div>
    <div><span class="grande">{comp.get('coinciden', '—')}/{comp.get('filas_esperadas', '—')}</span><span>filas iguales al esperado</span></div>
    {_insignia(c['cumplio'])}
  </div>
  <ul class="checks">{checks}</ul>
  {f'<h4>Motivos</h4><ul class="motivos">{motivos}</ul>' if motivos else ''}
  <h4>YAML usado: <code>{e(mapeo.get('archivo') or '')}</code> <span class="sub">SHA-256 {e((mapeo.get('sha256') or '')[:16])}…</span></h4>
  <pre class="codigo">{e(mapeo.get('contenido') or '')}</pre>
  <p class="nota">Inicio {e(d.get('inicio', ''))} · fin {e(d.get('fin', ''))}. {e(d.get('nota', ''))}</p>
</div>"""


# ---------------------------------------------------------------------
def generar_dashboard(corrida: ResultadoCorrida, met: dict, raiz: Path, destino: Path) -> Path:
    fuentes = _datos_fuentes(corrida, raiz)
    filas = filas_reporte(corrida)
    por_tipo: dict[str, Counter] = defaultdict(Counter)
    nombres = {f["id"]: f["corto"] for f in fuentes}
    for r in filas:
        por_tipo[r["tipo_error"]][nombres.get(r["fuente"], r["fuente"])] += 1
    conteo = sorted(((t, sum(c.values()), dict(c)) for t, c in por_tipo.items()), key=lambda x: -x[1])
    tiempos_ms = [r.segundos * 1000 for r in corrida.registros()]
    svg_tiempos, info_t = grafico_tiempos(tiempos_ms)
    ejemplo = next((r.bundle for r in corrida.registros() if r.validacion and r.validacion.valido), None)
    json_ej = json.dumps(ejemplo, ensure_ascii=False, indent=2) if ejemplo else "{}"

    total = sum(f["extraidos"] for f in fuentes)
    validos = sum(f["validos"] for f in fuentes)
    h2 = met["hipotesis_h2"]
    clase_h2 = {"confirmada en entorno simulado": "ok", "no confirmada": "mal"}.get(h2["estado"], "pend")
    metas = met["metas"]
    intactas = all(f["intacta"] for f in fuentes if f["conectada"])

    tabla_fuentes = "".join(f"<tr><td>{e(f['corto'])}</td><td class=num>{f['extraidos']}</td>"
                            f"<td class=num>{f['validos']}</td><td class=num>{f['errores']}</td></tr>" for f in fuentes)
    tabla_err = "".join(f"<tr><td>{e(NOMBRE_ERROR.get(t, t))}</td><td class=num>{c}</td></tr>" for t, c, _ in conteo)
    tabla_t = "".join(f"<tr><td>{e(r)} ms</td><td class=num>{c}</td></tr>" for r, c in info_t.get("tabla", []))
    integridad = "".join(
        f'<li><span class="{"ok" if f["intacta"] else "mal"}">{"✓" if f["intacta"] else "✗"}</span> '
        f'{e(f["corto"])} <code title="{e(f["sha_antes"] or "")}">{e((f["sha_antes"] or "")[:12])}…</code>'
        f' → <code title="{e(f["sha_despues"] or "")}">{e((f["sha_despues"] or "")[:12])}…</code></li>'
        for f in fuentes if f["conectada"])
    leyenda_fuentes = "".join(f'<span class="ley"><i style="background:{f["color"]}"></i>{e(f["corto"])}</span>'
                              for f in fuentes)
    nota_t = (f"Meta C4: promedio ≤ {num(met['criterios']['C4']['meta'])} s (= {num(met['criterios']['C4']['meta'] * 1000)} ms). "
              f"La atención más lenta tardó {num(info_t.get('maximo', 0), 1)} ms.")
    t_val = [r.segundos * 1000 for r in corrida.registros() if r.atencion.valida]
    t_err = [r.segundos * 1000 for r in corrida.registros() if not r.atencion.valida]
    if t_val and t_err:
        nota_t += (f" Las atenciones válidas tardaron en promedio {num(statistics.mean(t_val), 2)} ms y las que tenían "
                   f"error {num(statistics.mean(t_err), 2)} ms, porque estas no generan RDA (pasos 5 a 7).")
    if info_t.get("fuera"):
        nota_t += f" {info_t['fuera']} atención(es) por encima de {num(info_t['limite'], 1)} ms se agrupan en la última barra."

    cuerpo = f"""
<a class="saltar" href="#principal">Saltar al contenido</a>
<header class="cabecera">
  <div class="marca">{LOGO}<div><p class="nombre">SALUDIA</p><p class="desc">Conector HIS → RDA · HL7 FHIR R4</p></div></div>
  <p class="leyenda-academica" role="note">{e(LEYENDA)}</p>
</header>
<main id="principal">
<section class="heroe">
  <div>
    <h1>{e(TITULAR)}</h1>
    <p class="lead">{e(SUBTITULO)}</p>
    <ul class="chips">
      <li>Ejecución: <strong>{e(fecha_larga(corrida.inicio))}</strong></li>
      <li>FHIR <strong>{e(met['version_fhir'])}</strong> (R4)</li>
      <li>CIE-10: <strong>{met['catalogo_cie10']['codigos']}</strong> códigos · {e(met['catalogo_cie10']['origen'])}</li>
    </ul>
  </div>
  <div class="heroe-cifra">
    <p class="cifra"><span class="contador" data-valor="{validos}" data-dec="0">{validos}</span><small> / {total}</small></p>
    <p>atenciones convertidas en RDA válidos</p>
    <p class="h2 {clase_h2}">Hipótesis H2 ({e(', '.join(h2['criterios']))}): <strong>{e(h2['estado'])}</strong></p>
  </div>
</section>

<section aria-labelledby="t-recorrido">
  <h2 id="t-recorrido">Recorrido del dato</h2>
  <div class="alcance"><span class="alcance-etq">Alcance del prototipo (pasos 1–7)</span>
  {_stepper(fuentes, met, len(filas))}</div>
  <p class="nota">Fuera del alcance (fase posterior): cola cifrada de reintento, envío seguro a la IHCE, panel de cumplimiento y contenedor Docker.</p>
</section>

<section aria-labelledby="t-kpi">
  <h2 id="t-kpi">Criterios de éxito</h2>
  <p class="nota">Metas fijadas el {e(metas['fecha_fijacion'])} en <code>{e(metas['archivo'])}</code>, antes de ejecutar las pruebas.
  Huella SHA-256 <code>{e(metas['sha256'][:16])}…</code> {'✓ sin cambios' if metas['sin_cambios'] else '⚠ no coincide con la registrada'}.</p>
  <div class="kpis">{_kpis(met)}</div>
</section>

<section aria-labelledby="t-graf" class="graficos">
  <h2 id="t-graf">Lo que pasó en esta corrida</h2>
  <div class="rejilla-graf">
    <figure class="tarjeta">
      <figcaption><h3>Atenciones por fuente</h3><p>RDA válido vs. registro con error</p></figcaption>
      <div class="leyendas">{leyenda_fuentes}<span class="ley"><i class="i-error"></i>Con error (reportado)</span></div>
      {grafico_fuentes(fuentes)}
      <details class="datos"><summary>Ver datos</summary><table><thead><tr><th>Fuente</th><th>Extraídas</th><th>RDA válidos</th><th>Con error</th></tr></thead><tbody>{tabla_fuentes}</tbody></table></details>
    </figure>
    <figure class="tarjeta">
      <figcaption><h3>Errores por tipo</h3><p>Cada registro con error se reporta; no se borra ni se corrige</p></figcaption>
      {grafico_errores(conteo)}
      <details class="datos"><summary>Ver datos</summary><table><thead><tr><th>Tipo</th><th>Cantidad</th></tr></thead><tbody>{tabla_err}</tbody></table></details>
    </figure>
    <figure class="tarjeta ancho">
      <figcaption><h3>Tiempo por atención</h3><p>Distribución de las {len(tiempos_ms)} atenciones</p></figcaption>
      {svg_tiempos}
      <p class="nota">{e(nota_t)}</p>
      <details class="datos"><summary>Ver datos</summary><table><thead><tr><th>Rango</th><th>Atenciones</th></tr></thead><tbody>{tabla_t}</tbody></table></details>
    </figure>
  </div>
</section>

<section aria-labelledby="t-het">
  <h2 id="t-het">Tres fuentes distintas, un solo modelo</h2>
  <p class="nota">Primeras atenciones válidas de cada fuente y un registro con error (resaltado), tal como llegan y como quedan después del mapeo YAML y la normalización.</p>
  {_pestanas(fuentes)}
</section>

<section aria-labelledby="t-err">
  <h2 id="t-err">Reporte de errores</h2>
  {_tabla_errores(filas, fuentes)}
</section>

<section class="rejilla-2">
  <div class="tarjeta">
    <div class="cab-tarjeta"><h2>RDA de ejemplo <span class="sub">Bundle · document · 4 recursos</span></h2>
    <button class="boton no-print" id="copiar" type="button">Copiar JSON</button></div>
    <ul class="recursos"><li>Composition</li><li>Patient</li><li>Encounter</li><li>Condition</li></ul>
    <pre class="codigo json" id="rda-json">{resaltar_json(json_ej)}</pre>
  </div>
  <div class="tarjeta">
    <h2>Integridad y alcance</h2>
    <p class="estado-int {'ok' if intactas else 'mal'}">{'✓ Fuentes intactas' if intactas else '✗ Una fuente cambió'}</p>
    <p class="nota">Huella SHA-256 de cada archivo fuente antes → después de la corrida. Las fuentes se abren en solo lectura.</p>
    <ul class="integridad">{integridad}</ul>
    <h3>Validación estructural</h3>
    <p class="nota">{e(met['alcance_validacion'])}. Se valida con <code>fhir.resources</code> (FHIR {e(met['version_fhir'])}) y con reglas propias de documento (bdl-7, bdl-9, bdl-10, bdl-11, conjuntos de valores, zona horaria y referencias internas).</p>
    <h3>Entorno</h3>
    <p class="nota">Python {e(met['entorno']['python'])} · fhir.resources {e(met['entorno']['fhir_resources'])} · {e(met['entorno']['sistema'])}<br>
    Corrida completa: {num(met['criterios']['C4']['detalle']['total_corrida_s'], 2)} s</p>
  </div>
</section>

<section aria-labelledby="t-c5">
  <h2 id="t-c5">C5 · Fuente nueva conectada solo con YAML</h2>
  {_seccion_c5(met)}
</section>
</main>
<footer class="pie">
  <p class="leyenda-academica">{e(LEYENDA)}</p>
  <p>FHIR {e(met['version_fhir'])} · ejecución del {e(fecha_larga(corrida.inicio))} · generado por <code>python main.py ejecutar</code></p>
  <p>Datos 100 % sintéticos generados con Faker (es_CO) y semilla fija; ninguno corresponde a personas reales.
  Este prototipo no está certificado ni aprobado por el Ministerio de Salud y Protección Social, y la validación
  estructural contra FHIR R4 base no implica conformidad con la guía de implementación del RDA.
  El catálogo CIE-10 usado es: {e(met['catalogo_cie10']['origen'])}.</p>
  <p>{e(' · '.join(EQUIPO))}<br>{e(INSTITUCION)}</p>
</footer>
<div id="tip" class="tip" role="tooltip" hidden></div>"""

    pagina = ("<!DOCTYPE html>\n<html lang=\"es-CO\">\n<head>\n<meta charset=\"utf-8\">\n"
              "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
              f"<title>SALUDIA · Resultados del prototipo · {e(corrida.inicio.strftime('%Y-%m-%d %H:%M'))}</title>\n"
              f"<style>{CSS}</style>\n</head>\n<body>{cuerpo}\n<script>{JS}</script>\n</body>\n</html>\n")
    destino.write_text(pagina, encoding="utf-8")
    return destino


# ---------------------------------------------------------------------
CSS = r"""
:root{
  color-scheme:light;
  --fondo:#fbfaf7; --superficie:#ffffff; --superficie-2:#f6f4ef;
  --tinta:#1b2330; --tinta-2:#465162; --tinta-3:#646d7a; --borde:#e6e2d8; --grid:#ece9e1; --base:#c9c5ba;
  --cielo:#2a78d6; --cielo-texto:#1f5fae; --cielo-suave:#e7f0fb;
  --menta:#1baf7a; --menta-texto:#0e7350; --menta-suave:#e2f5ed;
  --lavanda-texto:#5546b8; --lavanda-suave:#efecfb;
  --coral:#e5705c; --coral-texto:#ad3d2a; --coral-suave:#fdebe7;
  --ambar:#e9a21b; --ambar-texto:#7d5200; --ambar-suave:#fff3d6;
  --naranja:#e8730c; --naranja-texto:#a24f04;
  --serie-1:#2a78d6; --serie-2:#1baf7a; --serie-3:#c0559f;
  --sombra:0 1px 2px rgba(27,35,48,.05),0 6px 20px rgba(27,35,48,.06);
  --radio:16px;
  --fuente:Inter,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,"SFMono-Regular","Cascadia Code",Consolas,"Liberation Mono",monospace;
}
@media (prefers-color-scheme:dark){
  :root{
    color-scheme:dark;
    --fondo:#121417; --superficie:#1a1d21; --superficie-2:#20242a;
    --tinta:#eef0f2; --tinta-2:#c3c8d0; --tinta-3:#9ba3ae; --borde:#2b3038; --grid:#262a31; --base:#3a3f47;
    --cielo-texto:#8cbcf2; --cielo-suave:#1c2a3b; --menta-texto:#5fd3a6; --menta-suave:#173029;
    --lavanda-texto:#b9b0f5; --lavanda-suave:#25223a; --coral-texto:#f39a89; --coral-suave:#3a2220;
    --ambar-texto:#f5c766; --ambar-suave:#352a14; --naranja-texto:#f6a45c;
    --serie-1:#3987e5; --serie-2:#199e70; --serie-3:#d066b0;
    --sombra:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.25);
  }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--fondo);color:var(--tinta);font-family:var(--fuente);font-size:15px;line-height:1.55}
code,pre{font-family:var(--mono);font-size:.86em}
h1,h2,h3,h4{line-height:1.2;margin:0 0 .5rem}
h2{font-size:1.25rem;margin-top:2.4rem}
h3{font-size:1rem}
.saltar{position:absolute;left:-999px}.saltar:focus{left:1rem;top:1rem;background:var(--superficie);padding:.5rem;z-index:9}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.sub{font-weight:400;color:var(--tinta-3);font-size:.85em}
.nota{color:var(--tinta-3);font-size:.88rem;margin:.25rem 0 .8rem}
.num{text-align:right;font-variant-numeric:tabular-nums}
.cabecera,main,.pie{max-width:1220px;margin:0 auto;padding:0 24px}
.cabecera{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding-top:22px}
.marca{display:flex;align-items:center;gap:12px}
.logo{width:44px;height:44px}
.nombre{margin:0;font-weight:800;letter-spacing:.06em;font-size:1.15rem}
.desc{margin:0;color:var(--tinta-3);font-size:.85rem}
.leyenda-academica{margin:0;background:var(--lavanda-suave);color:var(--lavanda-texto);border-radius:999px;padding:.4rem .9rem;font-size:.85rem;font-weight:600}
.heroe{display:grid;grid-template-columns:1.6fr 1fr;gap:24px;align-items:center;margin-top:22px;background:linear-gradient(135deg,var(--cielo-suave),var(--menta-suave));border-radius:24px;padding:32px}
.heroe h1{font-size:clamp(1.6rem,3vw,2.3rem);letter-spacing:-.01em}
.lead{color:var(--tinta-2);max-width:60ch}
.chips{list-style:none;padding:0;margin:1rem 0 0;display:flex;flex-wrap:wrap;gap:8px}
.chips li{background:var(--superficie);border:1px solid var(--borde);border-radius:999px;padding:.3rem .75rem;font-size:.84rem;color:var(--tinta-2)}
.heroe-cifra{background:var(--superficie);border-radius:var(--radio);padding:22px;box-shadow:var(--sombra)}
.heroe-cifra p{margin:.2rem 0}
.cifra{font-size:2.8rem;font-weight:800;font-variant-numeric:tabular-nums;color:var(--cielo-texto)}
.cifra small{font-size:1.2rem;color:var(--tinta-3);font-weight:600}
.h2{margin-top:.8rem!important;padding:.45rem .7rem;border-radius:10px;font-size:.9rem}
.h2.ok{background:var(--menta-suave);color:var(--menta-texto)} .h2.mal{background:var(--coral-suave);color:var(--coral-texto)} .h2.pend{background:var(--ambar-suave);color:var(--ambar-texto)}
.alcance{position:relative;border:2px dashed var(--naranja);border-radius:var(--radio);padding:30px 16px 16px;margin-top:14px;background:var(--superficie)}
.alcance-etq{position:absolute;top:-12px;left:16px;background:var(--fondo);color:var(--naranja-texto);font-weight:700;padding:0 .5rem;font-size:.9rem}
.stepper{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:10px;counter-reset:p}
.stepper li{position:relative;display:flex;flex-direction:column;gap:4px;padding-top:44px;font-size:.84rem}
.stepper li strong{font-size:.86rem}
.stepper li span:last-child{color:var(--tinta-3)}
.stepper li::before{content:"";position:absolute;top:17px;left:36px;right:-10px;height:2px;background:var(--borde)}
.stepper li:last-child::before{display:none}
.nodo{position:absolute;top:0;left:0;width:36px;height:36px;border-radius:50%;display:grid;place-items:center;font-weight:800;background:var(--naranja);color:#fff;z-index:1}
.nodo.sin-num{background:var(--tinta);}
.kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px}
.kpi{background:var(--superficie);border:1px solid var(--borde);border-radius:var(--radio);box-shadow:var(--sombra);padding:16px;display:flex;flex-direction:column;gap:10px}
.kpi header{display:flex;gap:8px;align-items:baseline}
.kpi-id{font-weight:800;color:var(--lavanda-texto);background:var(--lavanda-suave);border-radius:8px;padding:.05rem .45rem;font-size:.85rem}
.kpi h3{font-size:.92rem;margin:0}
.kpi-cuerpo{display:flex;align-items:center;gap:12px}
.anillo-wrap{position:relative;width:88px;height:88px;flex:none}
.anillo{width:88px;height:88px}
.anillo .pista{fill:none;stroke:var(--grid);stroke-width:8}
.anillo .arco{fill:none;stroke-width:8;stroke-linecap:round;transition:stroke-dasharray 1s ease}
.anillo.ok .arco{stroke:var(--menta)} .anillo.mal .arco{stroke:var(--coral)} .anillo.pend .pista{stroke:var(--ambar)}
.centro{position:absolute;inset:0;display:grid;place-items:center;font-weight:800;font-size:1.1rem;white-space:nowrap;font-variant-numeric:tabular-nums;text-align:center;line-height:1}
.centro small{font-size:.7rem;color:var(--tinta-3);margin-left:1px}
.txt-centro{font-size:1rem}
.kpi dl{margin:0} .kpi dt{font-size:.75rem;color:var(--tinta-3);text-transform:uppercase;letter-spacing:.05em} .kpi dd{margin:0;font-weight:600}
.kpi-linea{margin:0;color:var(--tinta-2);font-size:.84rem;flex:1}
.insignia{display:inline-flex;align-self:flex-start;align-items:center;gap:.3rem;border-radius:999px;padding:.25rem .7rem;font-weight:700;font-size:.82rem}
.insignia.ok{background:var(--menta-suave);color:var(--menta-texto)} .insignia.mal{background:var(--coral-suave);color:var(--coral-texto)} .insignia.pend{background:var(--ambar-suave);color:var(--ambar-texto)}
.rejilla-graf{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px} .rejilla-graf .ancho{grid-column:1/-1}
.rejilla-2{display:grid;grid-template-columns:1.25fr 1fr;gap:14px;margin-top:2.4rem}
.rejilla-2 h2{margin-top:0}
.tarjeta{background:var(--superficie);border:1px solid var(--borde);border-radius:var(--radio);box-shadow:var(--sombra);padding:18px;margin:0;min-width:0}
figcaption p{margin:0 0 .4rem;color:var(--tinta-3);font-size:.85rem}
.grafico{width:100%;height:auto;display:block;margin-top:6px;overflow:visible}
.eje-txt{fill:var(--tinta-3);font-size:12px;font-family:var(--fuente)}
.valor-txt{fill:var(--tinta-2);font-size:12px;font-family:var(--fuente);font-weight:600}
.ref-txt{fill:var(--tinta-2);font-size:11px;font-family:var(--fuente)}
.grid{stroke:var(--grid);stroke-width:1} .base{stroke:var(--base);stroke-width:1} .ref{stroke:var(--tinta-2);stroke-width:1.5}
.m-error{fill:var(--coral)} .m-tiempo{fill:var(--serie-1)}
[data-tip]{cursor:default} [data-tip]:hover{opacity:.82}
.leyendas{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:.8rem;color:var(--tinta-2)}
.ley{display:inline-flex;align-items:center;gap:6px} .ley i{width:12px;height:12px;border-radius:3px;display:inline-block} .i-error{background:var(--coral)}
details.datos{margin-top:.4rem;font-size:.84rem} details.datos table{border-collapse:collapse;margin-top:.4rem;width:100%}
details.datos td,details.datos th{border-bottom:1px solid var(--borde);padding:.25rem .4rem;text-align:left}
summary{cursor:pointer;color:var(--cielo-texto);font-weight:600}
.pestanas [role=tablist]{display:flex;gap:6px;flex-wrap:wrap;border-bottom:1px solid var(--borde);margin-bottom:14px}
.pestanas [role=tab]{font:inherit;font-weight:600;background:none;border:0;border-bottom:3px solid transparent;padding:.6rem .9rem;color:var(--tinta-2);cursor:pointer;display:inline-flex;align-items:center;gap:8px}
.pestanas [role=tab][aria-selected=true]{color:var(--tinta);border-bottom-color:var(--cielo)}
.pestanas [role=tab]:focus-visible,.boton:focus-visible,select:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid var(--cielo);outline-offset:2px;border-radius:6px}
.punto{width:10px;height:10px;border-radius:50%;display:inline-block}
.lado-a-lado{display:grid;grid-template-columns:1fr;gap:0} .flecha{justify-self:center;color:var(--tinta-3);font-size:.85rem;padding:.35rem 0}
.lado-a-lado>div{background:var(--superficie);border:1px solid var(--borde);border-radius:var(--radio);padding:14px;min-width:0}
h4{font-size:.95rem}
.tabla-scroll{overflow:auto;max-width:100%} .tabla-scroll.alto{max-height:440px;border:1px solid var(--borde);border-radius:12px;background:var(--superficie)}
.tabla-mini,.tabla-errores{border-collapse:collapse;width:100%;font-size:.82rem}
.tabla-mini th,.tabla-mini td,.tabla-errores th,.tabla-errores td{padding:.4rem .55rem;border-bottom:1px solid var(--borde);text-align:left;vertical-align:top;white-space:nowrap}
.tabla-errores td:last-child{white-space:normal;min-width:260px}
.tabla-mini thead th,.tabla-errores thead th{background:var(--superficie-2);position:sticky;top:0;font-weight:700;color:var(--tinta-2)}
.fila-error th{color:var(--coral-texto)} .celda-error{background:var(--coral-suave);color:var(--coral-texto);white-space:normal!important}
.chip-error{background:var(--coral-suave);color:var(--coral-texto);border-radius:999px;padding:.1rem .55rem;font-weight:600;font-size:.78rem}
.filtros{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:end;margin-bottom:10px}
.filtros label{display:flex;flex-direction:column;font-size:.78rem;color:var(--tinta-3);gap:3px}
.filtros select,.filtros input{font:inherit;font-size:.9rem;padding:.45rem .6rem;border:1px solid var(--borde);border-radius:10px;background:var(--superficie);color:var(--tinta);min-width:170px}
.buscar{flex:1} .buscar input{width:100%}
.cuenta{color:var(--tinta-3);font-size:.85rem;padding-bottom:.5rem}
.cab-tarjeta{display:flex;justify-content:space-between;align-items:center;gap:10px}
.boton{font:inherit;font-weight:600;font-size:.85rem;background:var(--cielo);color:#fff;border:0;border-radius:10px;padding:.5rem .9rem;cursor:pointer}
.boton.hecho{background:var(--menta-texto)}
.recursos{list-style:none;padding:0;margin:.3rem 0 .6rem;display:flex;gap:6px;flex-wrap:wrap}
.recursos li{background:var(--lavanda-suave);color:var(--lavanda-texto);border-radius:8px;padding:.1rem .5rem;font-size:.8rem;font-weight:600}
.codigo{background:var(--superficie-2);border:1px solid var(--borde);border-radius:12px;padding:12px;overflow:auto;max-height:460px;margin:0;line-height:1.45;white-space:pre}
.jk{color:var(--cielo-texto)} .js{color:var(--menta-texto)} .jn{color:var(--lavanda-texto)} .jb{color:var(--naranja-texto)}
.estado-int{font-weight:700;font-size:1.05rem;margin:.2rem 0}
.integridad .ok,.estado-int.ok,.checks .ok{color:var(--menta-texto)} .integridad .mal,.estado-int.mal,.checks .mal{color:var(--coral-texto)}
.integridad{list-style:none;padding:0;margin:0 0 1rem;font-size:.85rem} .integridad li{padding:.25rem 0;border-bottom:1px dashed var(--borde)}
.c5{border-radius:var(--radio);padding:20px;border:1px solid var(--borde);background:var(--superficie);box-shadow:var(--sombra)}
.c5.pend{background:var(--ambar-suave);border-color:transparent}
.c5.pend p{color:var(--ambar-texto)}
.c5-pasos{margin:1rem 0 0;padding-left:1.2rem;display:grid;gap:6px}
.c5-pasos li span{display:block;color:var(--tinta-3);font-size:.84rem}
.c5-pasos code{background:var(--superficie);padding:.15rem .45rem;border-radius:6px}
.c5-cifras{display:flex;flex-wrap:wrap;gap:22px;align-items:center;margin-bottom:12px}
.c5-cifras div{display:flex;flex-direction:column} .grande{font-size:1.7rem;font-weight:800;font-variant-numeric:tabular-nums} .c5-cifras span:last-child{color:var(--tinta-3);font-size:.82rem}
.checks,.motivos{padding-left:0;list-style:none;margin:.4rem 0 1rem} .checks li{padding:.15rem 0;font-weight:600}
.motivos li{color:var(--tinta-2);font-size:.88rem;padding:.15rem 0}
.alerta{padding:.7rem 1rem;border-radius:12px;background:var(--coral-suave)}
.vacio{color:var(--tinta-3)}
.pie{margin-top:3rem;padding-top:1.4rem;padding-bottom:2.5rem;border-top:1px solid var(--borde);color:var(--tinta-3);font-size:.84rem}
.pie .leyenda-academica{display:inline-block;margin-bottom:.6rem}
.tip{position:fixed;z-index:20;pointer-events:none;background:var(--tinta);color:var(--superficie);padding:.4rem .6rem;border-radius:8px;font-size:.8rem;max-width:280px;box-shadow:var(--sombra)}
.solo-print{display:none}
@media (max-width:1100px){.kpis{grid-template-columns:repeat(3,minmax(0,1fr))}.stepper{grid-template-columns:repeat(4,minmax(0,1fr))}.stepper li:nth-child(4n)::before{display:none}}
@media (max-width:760px){.heroe,.rejilla-2,.rejilla-graf{grid-template-columns:1fr}.kpis{grid-template-columns:1fr 1fr}.stepper{grid-template-columns:1fr 1fr}.stepper li::before{display:none}.heroe{padding:22px}}
@media (max-width:560px){.kpis{grid-template-columns:1fr}.cabecera,main,.pie{padding:0 14px}.filtros select{min-width:0;width:100%}.filtros label{flex:1 1 140px}}
@media (prefers-reduced-motion:reduce){.anillo .arco{transition:none}}
@media print{
  :root{color-scheme:light}
  body{background:#fff;font-size:11.5px;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .no-print,#tip,.saltar,.pestanas [role=tablist],details.datos,details.yaml summary{display:none!important}
  [role=tabpanel][hidden]{display:block!important} .solo-print{display:block}
  .tarjeta,.kpi,.c5,.heroe-cifra{box-shadow:none} .tarjeta,.kpi,figure,.lado-a-lado>div{break-inside:avoid}
  .tabla-scroll.alto,.codigo{max-height:none;overflow:visible} .codigo{white-space:pre-wrap}
  section{break-inside:auto} h2{break-after:avoid}
  .kpis{grid-template-columns:repeat(5,1fr)}
  @page{margin:12mm}
}
"""

JS = r"""
(function(){
  var reducido = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  function fmt(v, dec){ return Number(v).toLocaleString('es-CO',{minimumFractionDigits:dec,maximumFractionDigits:dec}); }
  // Contadores animados (el valor final ya está en el HTML: funciona sin JS y al imprimir)
  document.querySelectorAll('.contador').forEach(function(el){
    var fin = parseFloat(el.dataset.valor), dec = parseInt(el.dataset.dec||'0',10);
    if (isNaN(fin) || reducido) return;
    var t0 = null, dur = 1100;
    function paso(t){ if(!t0) t0=t; var p=Math.min((t-t0)/dur,1), e=1-Math.pow(1-p,3);
      el.textContent = fmt(fin*e, dec); if(p<1) requestAnimationFrame(paso); else el.textContent = fmt(fin, dec); }
    el.textContent = fmt(0, dec); requestAnimationFrame(paso);
  });
  // Anillos: crecen desde cero
  if (!reducido) document.querySelectorAll('.anillo .arco').forEach(function(c){
    var final = c.getAttribute('stroke-dasharray'); var circ = final.split(' ')[1];
    c.setAttribute('stroke-dasharray','0 '+circ); setTimeout(function(){ c.setAttribute('stroke-dasharray', final); }, 60);
  });
  // Tooltip de los gráficos
  var tip = document.getElementById('tip');
  document.querySelectorAll('[data-tip]').forEach(function(el){
    el.addEventListener('mousemove', function(ev){ tip.textContent = el.getAttribute('data-tip'); tip.hidden = false;
      var x = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8); tip.style.left = x+'px'; tip.style.top = (ev.clientY + 14)+'px'; });
    el.addEventListener('mouseleave', function(){ tip.hidden = true; });
  });
  // Pestañas accesibles (clic y flechas)
  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role=tab]'));
  function activar(t){ tabs.forEach(function(o){ var sel = o===t; o.setAttribute('aria-selected', sel); o.tabIndex = sel?0:-1;
      document.getElementById(o.getAttribute('aria-controls')).hidden = !sel; }); t.focus(); }
  tabs.forEach(function(t,i){ t.addEventListener('click', function(){ activar(t); });
    t.addEventListener('keydown', function(ev){ if(ev.key==='ArrowRight') activar(tabs[(i+1)%tabs.length]);
      if(ev.key==='ArrowLeft') activar(tabs[(i-1+tabs.length)%tabs.length]); }); });
  // Filtros del reporte de errores
  var fF = document.getElementById('f-fuente'), fT = document.getElementById('f-tipo'), fX = document.getElementById('f-texto'), cuenta = document.getElementById('f-cuenta');
  var filas = Array.prototype.slice.call(document.querySelectorAll('#errores-cuerpo tr'));
  function filtrar(){ var q = (fX.value||'').toLowerCase(), n = 0;
    filas.forEach(function(r){ var ok = (!fF.value || r.dataset.fuente===fF.value) && (!fT.value || r.dataset.tipo===fT.value) && (!q || r.textContent.toLowerCase().indexOf(q)>=0);
      r.hidden = !ok; if(ok) n++; });
    cuenta.textContent = n + ' de ' + filas.length; }
  if (fF) { fF.addEventListener('change', filtrar); fT.addEventListener('change', filtrar); fX.addEventListener('input', filtrar); }
  // Copiar el RDA
  var btn = document.getElementById('copiar');
  if (btn) btn.addEventListener('click', function(){
    var texto = document.getElementById('rda-json').textContent;
    function listo(){ btn.textContent = 'Copiado ✓'; btn.classList.add('hecho'); setTimeout(function(){ btn.textContent='Copiar JSON'; btn.classList.remove('hecho'); }, 1800); }
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(texto).then(listo, respaldo); } else { respaldo(); }
    function respaldo(){ var ta = document.createElement('textarea'); ta.value = texto; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); listo(); } catch(e) {} document.body.removeChild(ta); }
  });
})();
"""
