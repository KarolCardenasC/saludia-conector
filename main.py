"""SALUDIA · Conector HIS → RDA (HL7 FHIR R4) · Prototipo académico.

Uso:
    python main.py generar-datos      Genera las 300 atenciones sintéticas
    python main.py revisar-mapeos     Pasos 1-4: crudo vs normalizado y errores por fuente
    python main.py ejecutar           Corre el conector: fuentes → RDA FHIR + reporte,
                                      métricas C1–C5 y dashboard HTML
    python main.py exploratorio       Casos difíciles, fuera de los criterios C1–C5
Opción global:
    --sin-color                       Desactiva los colores de la terminal
"""
from __future__ import annotations

import argparse
import platform
import statistics
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def _consola(args):
    from saludia.consola import Consola
    return Consola(color=False if args.sin_color else None)


def _banner(con, subtitulo: str) -> None:
    from saludia import LEYENDA, __version__
    con.banner(f"◆ SALUDIA · Conector HIS → RDA (HL7 FHIR R4) · v{__version__}", subtitulo, LEYENDA)


# ---------------------------------------------------------------------
def cmd_generar_datos(args: argparse.Namespace) -> int:
    from generador_sintetico.generador import generar
    from generador_sintetico.verificar import verificar

    con = _consola(args)
    _banner(con, "Generación de datos sintéticos (Faker es_CO, semilla fija)")
    man = generar(semilla=args.semilla)
    con.seccion("Fuentes generadas")
    for fuente, r in man["fuentes"].items():
        con.p(f"  {con.c(fuente, 'b'):<15} {r['registros']:>3} registros · "
              f"{con.c(str(r['errores_sembrados']), 'rojo')} con error sembrado · {r['archivo']}")
    con.p(f"  Total: {man['total_atenciones']} atenciones · {man['total_errores_sembrados']} errores sembrados "
          f"→ datos/errores_sembrados.csv · semilla {man['semilla']}")

    v = verificar()
    con.seccion("Autoverificación de los datos (independiente del conector)")
    for fuente, d in v["detalle"].items():
        con.p(f"  {fuente:<15} normales válidos {d['normales_validos']}/"
              f"{d['registros'] - d['sembrados_esperados']} · sembrados que fallan en su campo "
              f"{d['sembrados_que_fallan_bien']}/{d['sembrados_esperados']}")
    for p in v["problemas"]:
        con.p("  " + con.mal("PROBLEMA: " + p))
    con.p("  Resultado: " + (con.ok("OK") if v["ok"] else con.mal("CON PROBLEMAS")))
    return 0 if v["ok"] else 1


# ---------------------------------------------------------------------
def cmd_revisar_mapeos(args: argparse.Namespace) -> int:
    """Pasos 1 a 4: lee cada fuente con su YAML y muestra crudo vs normalizado."""
    from saludia.catalogo import cargar_catalogo
    from saludia.conector import cargar_parametros, extraer_atenciones
    from saludia.mapeo import cargar_mapeo, descubrir_mapeos
    from saludia.modelo import ErrorConfiguracion

    con = _consola(args)
    rutas = cargar_parametros(RAIZ)["rutas"]
    cat = cargar_catalogo(RAIZ, rutas["referencia_cie10_oficial"], rutas["referencia_cie10_subconjunto"])
    _banner(con, "Revisión de mapeos (pasos 1 a 4)")
    con.dato("Catálogo CIE-10", f"{len(cat)} códigos · {cat.origen}")
    archivos = [Path(a) for a in args.archivo] if args.archivo else descubrir_mapeos(RAIZ / rutas["mapeos"])
    codigo = 0
    for archivo in archivos:
        con.seccion(f"Mapeo {archivo.name}")
        try:
            cfg = cargar_mapeo(archivo, RAIZ)
            lectura, ats = extraer_atenciones(cfg, cat)
        except ErrorConfiguracion as ex:
            con.p("  " + con.mal("NO SE PUDO CONECTAR LA FUENTE"))
            con.p("  " + str(ex).replace("\n", "\n  "))
            codigo = 1
            continue
        invalidas = [a for a in ats if not a.valida]
        con.dato("Fuente", f"{cfg.nombre} ({cfg.tipo}) · {cfg.ruta.name}")
        con.dato("Registros", f"{len(ats)} leídos · {con.c(len(ats) - len(invalidas), 'verde', 'b')} válidos · "
                              f"{con.c(len(invalidas), 'rojo', 'b')} con error")
        con.dato("Columnas usadas", ", ".join(lectura.columnas_usadas.values()))
        con.dato("Columnas ignoradas", ", ".join(lectura.columnas_ignoradas) or "(ninguna)")
        a = next((x for x in ats if x.valida), None)
        if a:
            con.p(f"\n  Ejemplo (fila {a.fila}): {con.c('dato crudo', 'gris')}  →  {con.c('modelo común', 'b')}")
            for campo in ("tipo_documento", "sexo", "fecha_nacimiento", "fecha_atencion", "codigo_cie10"):
                crudo = a.crudo.get(campo)
                norm = getattr(a, campo)
                if hasattr(norm, "strftime"):
                    norm = norm.strftime("%Y-%m-%d %H:%M" if hasattr(norm, "hour") else "%Y-%m-%d")
                con.p(f"    {campo:<17} {con.c(str(crudo).ljust(24), 'gris')} →  {con.c(norm, 'azul', 'b')}")
        if invalidas:
            tipos = Counter(h.tipo_error for x in invalidas for h in x.hallazgos)
            con.p("\n  Errores por tipo: " + ", ".join(f"{k}={con.c(v, 'rojo', 'b')}" for k, v in tipos.items()))
            for x in invalidas[: args.max_errores]:
                for h in x.hallazgos:
                    con.p(f"    fila {x.fila:>3} · {x.etiqueta:<16} · {h.campo:<17} · {h.mensaje}")
            if len(invalidas) > args.max_errores:
                con.p(f"    … y {len(invalidas) - args.max_errores} más")
    return codigo


# ---------------------------------------------------------------------
def cmd_ejecutar(args: argparse.Namespace) -> int:
    """Pasos 1 a 7: de las fuentes al RDA en JSON, reporte, métricas y dashboard."""
    import fhir.resources

    from saludia.conector import ejecutar
    from saludia.metricas import (calcular_metricas, cargar_metas, escribir_metricas, formato_meta,
                                  formato_resultado)
    from saludia.salidas import (escribir_ejemplo_rda, escribir_reporte_errores, escribir_resumen,
                                 filas_reporte)
    from saludia.validacion_fhir import ALCANCE, VERSION_FHIR

    con = _consola(args)
    _banner(con, "Ejecución del conector · pasos 1 a 7")
    metas = cargar_metas(RAIZ)
    con.dato("Librería FHIR", f"fhir.resources {fhir.resources.__version__} · "
                              + con.c(f"FHIR {VERSION_FHIR} (R4)", "b"))
    con.dato("Validación", ALCANCE)
    con.dato("Python", f"{platform.python_version()} · {platform.system()}")
    con.dato("Metas", f"config/metas.yaml · fijadas {metas['fecha_fijacion']} · SHA-256 {metas['_sha256'][:12]}… "
                      + (con.ok("sin cambios") if metas["_sin_cambios"] else con.mal("¡no coincide con la registrada!")))

    con.seccion("Procesando fuentes (solo lectura)")
    nombres = {}

    def al_iniciar(fid):
        nombres[fid] = fid

    def progreso(fid, i, n):
        if i == 1 or i == n or i % 5 == 0:
            con.barra(con.c(f"{fid:<15}", "b"), i, n)

    corrida = ejecutar(RAIZ, ids_fuentes=args.fuente or None, progreso=progreso, al_iniciar_fuente=al_iniciar)
    for f in corrida.fuentes:
        if not f.conectada:
            con.p(f"  {con.c(f'{f.id:<15}', 'b')} " + con.mal("NO CONECTADA"))
            con.p("    " + str(f.error_configuracion).replace("\n", "\n    "))

    d = corrida.dir_salidas
    escribir_reporte_errores(corrida, d)
    ej = escribir_ejemplo_rda(corrida, d)
    escribir_resumen(corrida, d)
    regs = list(corrida.registros())
    total = len(regs)
    invalidos = sum(not r.atencion.valida for r in regs)
    generados = sum(r.bundle is not None for r in regs)
    validos = sum(bool(r.validacion and r.validacion.valido) for r in regs)
    ignoradas = sum(len(f.lectura.columnas_ignoradas) for f in corrida.fuentes if f.lectura)
    conectadas = [f for f in corrida.fuentes if f.conectada]

    con.seccion("Resumen por paso")
    pasos = [
        ("1", "Adaptadores de lectura", f"{total} registros extraídos de {len(conectadas)} fuente(s)"),
        ("2", "Archivos de mapeo YAML", f"{len(conectadas)} mapeo(s) · {ignoradas} columnas ignoradas"),
        ("·", "Modelo común de atención", f"{total} atenciones"),
        ("3", "Normalizador", "fechas, sexo y tipo de documento unificados"),
        ("4", "Validador de datos (CIE-10)", f"{total - invalidos} válidas · {con.c(invalidos, 'rojo', 'b')} con error (reportadas)"),
        ("5", "Motor FHIR · Bundle RDA", f"{generados} Bundles document"),
        ("6", "Validador FHIR R4", f"{con.c(validos, 'verde', 'b')}/{generados} válidos"),
        ("7", "Salidas", f"rda/ ({validos} JSON) · reporte_errores · ejemplo_rda · corrida"),
    ]
    for n, nombre, detalle in pasos:
        con.p(f"  {con.c(n, 'b', 'amarillo')}  {nombre:<29} {detalle}")
    intactas = all(f.intacta for f in conectadas)
    con.p("\n  Fuentes intactas (SHA-256 antes = después): "
          + (con.ok("sí") if intactas else con.mal("NO")))
    tiempos = [r.segundos for r in regs]
    if tiempos:
        con.p(f"  Tiempo por atención: promedio {statistics.mean(tiempos) * 1000:.2f} ms · "
              f"máximo {max(tiempos) * 1000:.1f} ms · corrida completa {corrida.segundos_total:.2f} s")

    codigo = 0 if all(f.conectada for f in corrida.fuentes) else 1
    if args.fuente is not None:
        con.p(con.c("\n  (Métricas C1–C5 y dashboard solo para el experimento completo, sin --fuente)", "gris"))
        return codigo

    met = calcular_metricas(corrida, RAIZ)
    escribir_metricas(met, d)
    con.seccion("Criterios de éxito (metas fijas de config/metas.yaml)")
    filas = []
    for k, c in met["criterios"].items():
        filas.append([con.c(k, "b"), c["nombre"], formato_meta(c), formato_resultado(k, c), con.estado(c["cumplio"])])
    con.tabla(["", "Criterio", "Meta", "Resultado", "¿Cumplió?"], filas)
    c3 = met["criterios"]["C3"]["detalle"]
    con.p(f"  C3: {c3['detectados']}/{c3['sembrados']} errores sembrados detectados "
          f"({c3['detectados_con_tipo_y_campo_correctos']} con tipo y campo correctos) · "
          f"falsos positivos: {c3['falsos_positivos']}")
    h2 = met["hipotesis_h2"]
    estado_h2 = {"confirmada en entorno simulado": con.ok(h2["estado"]),
                 "no confirmada": con.mal(h2["estado"])}.get(h2["estado"], con.pendiente(h2["estado"]))
    con.p(f"  Hipótesis H2 (se cumplen {', '.join(h2['criterios'])}): {estado_h2}")

    from saludia.dashboard import generar_dashboard
    ruta_dash = generar_dashboard(corrida, met, RAIZ, d / "dashboard.html")
    con.seccion("Salidas")
    con.p(f"  {d.name}/rda/                 {validos} RDA en JSON (uno por atención válida)")
    if ej:
        con.p(f"  {d.name}/ejemplo_rda.json     un RDA formateado")
    con.p(f"  {d.name}/reporte_errores.csv  {len(filas_reporte(corrida))} hallazgos (también en .json)")
    con.p(f"  {d.name}/metricas.json        C1–C5 frente a sus metas")
    con.p(f"  {d.name}/dashboard.html       " + con.c("ábrelo con doble clic (no necesita internet)", "b", "azul"))
    return codigo


# ---------------------------------------------------------------------
def cmd_exploratorio(args: argparse.Namespace) -> int:
    """Casos difíciles fuera de los criterios C1–C5 (aprendizaje para la sección 6)."""
    from saludia.exploratorio import ETIQUETA, SIMBOLO, correr_exploratorio

    con = _consola(args)
    _banner(con, "Prueba exploratoria con casos difíciles")
    con.p(con.c(f"  ⚠ {ETIQUETA}.", "b", "magenta"))
    con.p("  No modifica las metas ni C1–C5. Lo esperado se definió antes de ejecutar.")
    res = correr_exploratorio(RAIZ)
    colores = {"coincide": "verde", "no detecta": "rojo", "marca de más": "amarillo", "normaliza distinto": "amarillo"}
    for v in res["variantes"]:
        con.seccion(f"Variante {v['variante']} · {v['descripcion']}")
        filas = [[c["caso"], c["nombre"], c["esperado"], c["resultado"],
                  con.c(f"{SIMBOLO[c['clasificacion']]} {c['clasificacion']}", colores[c["clasificacion"]], "b")]
                 for c in v["casos"]]
        con.tabla(["Caso", "Situación", "Se esperaba", "El sistema", "Resultado"], filas)
        con.p("  " + " · ".join(f"{SIMBOLO[k]} {k}: {n}" for k, n in v["resumen"].items()))
    con.p("\n  Detalle en salidas/hallazgos_exploratorios.md y .json")
    return 0


# ---------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    from saludia.consola import preparar_salida
    preparar_salida()
    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("--sin-color", action="store_true", help="Desactiva los colores de la terminal")
    parser = argparse.ArgumentParser(prog="main.py", description="SALUDIA · Conector HIS → RDA",
                                     parents=[comun])
    sub = parser.add_subparsers(dest="comando", required=True)

    p_gen = sub.add_parser("generar-datos", parents=[comun], help="Genera las 300 atenciones sintéticas")
    p_gen.add_argument("--semilla", type=int, default=None,
                       help="Semilla (por defecto la de config/parametros.yaml)")
    p_gen.set_defaults(func=cmd_generar_datos)

    p_rev = sub.add_parser("revisar-mapeos", parents=[comun],
                           help="Lee cada fuente con su YAML y muestra crudo vs normalizado")
    p_rev.add_argument("archivo", nargs="*", help="YAML a revisar (por defecto, todos los de mapeos/)")
    p_rev.add_argument("--max-errores", type=int, default=10)
    p_rev.set_defaults(func=cmd_revisar_mapeos)

    p_eje = sub.add_parser("ejecutar", parents=[comun], help="Ejecuta el conector sobre las fuentes")
    p_eje.add_argument("--fuente", action="append",
                       help="id de una fuente a procesar (se puede repetir). Por defecto: las 3 del experimento")
    p_eje.set_defaults(func=cmd_ejecutar)

    p_exp = sub.add_parser("exploratorio", parents=[comun],
                           help="Casos difíciles fuera de los criterios (aprendizaje)")
    p_exp.set_defaults(func=cmd_exploratorio)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
