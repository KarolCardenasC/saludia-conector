"""Cronómetro del criterio C5: conectar una fuente nueva SOLO con un YAML.

Uso (desde la carpeta del proyecto, con el entorno virtual activo):

    python scripts/c5_cronometro.py congelar   # 1. huella del código y de la configuración
    python scripts/c5_cronometro.py inicio     # 2. arranca el cronómetro
        ... escribir mapeos/<fuente4>.yaml ...
    python scripts/c5_cronometro.py intento    # 3. prueba el YAML (repetir las veces necesarias)
    python scripts/c5_cronometro.py estado     #    (opcional) ver cómo va
    python scripts/c5_cronometro.py fin        # 4. detiene, verifica y da el veredicto

Resultado: salidas/c5.json con el tiempo, el número de intentos y el
veredicto (si / parcial / no). Este script nunca ajusta el código para
que la fuente pase: si el esquema no alcanza, eso queda como hallazgo.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from saludia.catalogo import cargar_catalogo  # noqa: E402
from saludia.conector import cargar_parametros, procesar_fuente  # noqa: E402
from saludia.integridad import sha256_archivo  # noqa: E402
from saludia.mapeo import cargar_mapeo, descubrir_mapeos  # noqa: E402
from saludia.metricas import contar_registros_independiente  # noqa: E402
from saludia.modelo import ErrorConfiguracion  # noqa: E402
from saludia.motor_fhir import ContextoRDA, zona_desde_texto  # noqa: E402

EXCLUIR = {".venv", "venv", "__pycache__", "salidas", ".git", "node_modules"}
CAMPOS_COMPARADOS = ("tipo_documento", "numero_documento", "sexo", "fecha_nacimiento",
                     "fecha_atencion", "codigo_cie10")


# ---------------------------------------------------------------------
def _rutas(raiz: Path) -> dict:
    sal = raiz / cargar_parametros(raiz)["rutas"]["salidas"]
    sal.mkdir(parents=True, exist_ok=True)
    return {"salidas": sal, "congelado": sal / "c5_congelado.json", "estado": sal / "c5_estado.json",
            "resultado": sal / "c5.json", "rda": sal / "c5_salidas"}


def _leer(ruta: Path):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def _escribir(ruta: Path, datos) -> None:
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def _ahora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def archivos_congelables(raiz: Path) -> list[Path]:
    """Todos los .py del proyecto, los YAML de las fuentes del experimento y config/."""
    p = cargar_parametros(raiz)
    salida = []
    for py in raiz.rglob("*.py"):
        if not (set(py.relative_to(raiz).parts) & EXCLUIR):
            salida.append(py)
    ids = set(p["experimento"]["fuentes"])
    for y in descubrir_mapeos(raiz / p["rutas"]["mapeos"]):
        try:
            if cargar_mapeo(y, raiz).id in ids:
                salida.append(y)
        except ErrorConfiguracion:
            pass
    salida += sorted((raiz / "config").glob("*"))
    return sorted(set(salida))


def huellas_codigo(raiz: Path) -> dict[str, str]:
    return {a.relative_to(raiz).as_posix(): sha256_archivo(a) for a in archivos_congelables(raiz)}


def _git(raiz: Path) -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=raiz, capture_output=True,
                                text=True, timeout=10)
        estado = subprocess.run(["git", "status", "--porcelain"], cwd=raiz, capture_output=True,
                                text=True, timeout=10)
        if commit.returncode == 0:
            return {"commit": commit.stdout.strip(), "cambios_sin_commit": bool(estado.stdout.strip())}
    except (OSError, subprocess.SubprocessError):
        pass
    return {"commit": None}


def comparar_huellas(antes: dict, despues: dict) -> dict:
    nuevos_py = [k for k in despues if k not in antes and k.endswith(".py")]
    return {
        "modificados": sorted(k for k in antes if k in despues and antes[k] != despues[k]),
        "eliminados": sorted(k for k in antes if k not in despues),
        "py_nuevos": sorted(nuevos_py),
    }


# ---------------------------------------------------------------------
def congelar(raiz: Path = RAIZ) -> dict:
    r = _rutas(raiz)
    h = huellas_codigo(raiz)
    datos = {"fecha": _ahora(), "archivos": len(h), "huellas": h, "git": _git(raiz)}
    _escribir(r["congelado"], datos)
    return datos


def inicio(raiz: Path = RAIZ, reiniciar: bool = False) -> dict:
    r = _rutas(raiz)
    if not r["congelado"].exists():
        raise SystemExit("Primero ejecuta:  python scripts/c5_cronometro.py congelar")
    estado = _leer(r["estado"])
    if estado and not estado.get("terminado") and not reiniciar:
        raise SystemExit(f"Ya hay un cronómetro en marcha desde {estado['inicio']}. "
                         f"Usa 'intento', 'fin' o 'inicio --reiniciar'.")
    estado = {"inicio": _ahora(), "inicio_epoch": time.time(), "intentos": [], "terminado": False}
    _escribir(r["estado"], estado)
    r["resultado"].unlink(missing_ok=True)
    return estado


def buscar_mapeo_nuevo(raiz: Path, indicado: str | None) -> Path:
    if indicado:
        ruta = Path(indicado)
        return ruta if ruta.is_absolute() else raiz / ruta
    r = _rutas(raiz)
    congelados = set((_leer(r["congelado"]) or {}).get("huellas", {}))
    p = cargar_parametros(raiz)
    candidatos = [y for y in descubrir_mapeos(raiz / p["rutas"]["mapeos"])
                  if y.relative_to(raiz).as_posix() not in congelados]
    if not candidatos:
        raise SystemExit("No encontré un YAML nuevo en mapeos/. Copia mapeos/_plantilla.yaml "
                         "con otro nombre (sin '_' al inicio).")
    if len(candidatos) > 1:
        raise SystemExit("Hay varios YAML nuevos: " + ", ".join(c.name for c in candidatos)
                         + ". Indica cuál con --mapeo mapeos/<archivo>.yaml")
    return candidatos[0]


def _correr(raiz: Path, archivo: Path):
    """Corre SOLO la fuente del YAML indicado. Devuelve (cfg, resultado_fuente) o (None, error)."""
    import shutil
    r = _rutas(raiz)
    p = cargar_parametros(raiz)
    try:
        cfg = cargar_mapeo(archivo, raiz)
    except ErrorConfiguracion as e:
        return None, str(e)
    shutil.rmtree(r["rda"], ignore_errors=True)
    cat = cargar_catalogo(raiz, p["rutas"]["referencia_cie10_oficial"], p["rutas"]["referencia_cie10_subconjunto"])
    zona = zona_desde_texto(p["ips_simulada"]["zona_horaria"])
    ctx = ContextoRDA(p["ips_simulada"]["nombre"], datetime.now(zona), zona)
    return cfg, procesar_fuente(cfg, cat, ctx, r["rda"])


def _resumen_fuente(rf) -> dict:
    regs = rf.registros
    tipos = Counter(h.tipo_error for x in regs for h in x.atencion.hallazgos)
    ejemplos = [f"fila {x.atencion.fila} · {h.campo} · {h.mensaje}"
                for x in regs for h in x.atencion.hallazgos][:10]
    return {
        "conectada": rf.conectada, "error_configuracion": rf.error_configuracion,
        "registros": len(regs), "validos": sum(x.atencion.valida for x in regs),
        "con_error": sum(not x.atencion.valida for x in regs),
        "bundles_generados": sum(x.bundle is not None for x in regs),
        "bundles_validos": sum(bool(x.validacion and x.validacion.valido) for x in regs),
        "errores_por_tipo": dict(tipos), "primeros_errores": ejemplos,
        "columnas_ignoradas": rf.lectura.columnas_ignoradas if rf.lectura else [],
    }


def intento(raiz: Path = RAIZ, mapeo: str | None = None) -> dict:
    r = _rutas(raiz)
    estado = _leer(r["estado"])
    if not estado or estado.get("terminado"):
        raise SystemExit("No hay cronómetro en marcha. Ejecuta primero:  python scripts/c5_cronometro.py inicio")
    archivo = buscar_mapeo_nuevo(raiz, mapeo)
    cfg, rf = _correr(raiz, archivo)
    reg = {"numero": len(estado["intentos"]) + 1, "hora": _ahora(), "mapeo": archivo.name,
           "segundos_desde_inicio": round(time.time() - estado["inicio_epoch"], 1)}
    if cfg is None:
        reg.update({"resultado": "yaml_con_errores", "mensaje": rf})
    else:
        res = _resumen_fuente(rf)
        reg.update({"resultado": "conectada" if rf.conectada else "no_conectada", **res})
    estado["intentos"].append(reg)
    _escribir(r["estado"], estado)
    return reg


def _texto_norm(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def _texto_esperado(campo: str, v: str) -> str:
    v = (v or "").strip()
    if campo in ("fecha_nacimiento", "fecha_atencion") and v:
        try:
            dt = datetime.fromisoformat(v.replace(" ", "T"))
            tiene_hora = "T" in v or " " in v
            return dt.strftime("%Y-%m-%d %H:%M") if tiene_hora else dt.strftime("%Y-%m-%d")
        except ValueError:
            return v
    if campo in ("tipo_documento", "sexo", "codigo_cie10"):
        return v.upper()
    return v


def leer_esperado(ruta: Path) -> list[dict]:
    texto = ruta.read_text(encoding="utf-8-sig")
    try:
        dialecto = csv.Sniffer().sniff(texto.splitlines()[0], delimiters=",;\t|")
        sep = dialecto.delimiter
    except (csv.Error, IndexError):
        sep = ","
    filas = list(csv.DictReader(texto.splitlines(), delimiter=sep))
    return [{(k or "").strip(): (v or "").strip() for k, v in f.items()} for f in filas]


def comparar_con_esperado(rf, esperado: list[dict]) -> dict:
    obtenidos = {x.atencion.id_atencion: x for x in rf.registros if x.atencion.id_atencion}
    diferencias, coinciden = [], 0
    vistos = set()
    for fila in esperado:
        ident = fila.get("id_atencion", "")
        if not ident:
            diferencias.append("Fila del esperado sin id_atencion")
            continue
        vistos.add(ident)
        x = obtenidos.get(ident)
        if x is None:
            diferencias.append(f"{ident}: no aparece en lo procesado")
            continue
        esp_valido = fila.get("esperado_valido", "si").strip().lower() not in ("no", "false", "0", "n")
        difs = []
        if x.atencion.valida != esp_valido:
            difs.append(f"válido: esperado {'sí' if esp_valido else 'no'}, obtenido "
                        f"{'sí' if x.atencion.valida else 'no'}"
                        + ("" if x.atencion.valida else
                           f" ({'; '.join(h.mensaje for h in x.atencion.hallazgos)})"))
        if esp_valido:
            for c in CAMPOS_COMPARADOS:
                if c not in fila:
                    continue
                e, o = _texto_esperado(c, fila[c]), _texto_norm(getattr(x.atencion, c))
                if e != o:
                    difs.append(f"{c}: esperado '{e}', obtenido '{o}'")
        if difs:
            diferencias.append(f"{ident}: " + " | ".join(difs))
        else:
            coinciden += 1
    sobrantes = [i for i in obtenidos if i not in vistos]
    for i in sobrantes:
        diferencias.append(f"{i}: procesado pero no está en el esperado")
    return {"filas_esperadas": len(esperado), "coinciden": coinciden,
            "diferencias": len(diferencias), "detalle_diferencias": diferencias[:100]}


def fin(raiz: Path = RAIZ, mapeo: str | None = None, esperado: str | None = None) -> dict:
    r = _rutas(raiz)
    estado = _leer(r["estado"])
    congelado = _leer(r["congelado"])
    if not estado or estado.get("terminado"):
        raise SystemExit("No hay cronómetro en marcha.")
    t_fin = time.time()
    segundos = round(t_fin - estado["inicio_epoch"], 1)

    cambios = comparar_huellas(congelado["huellas"], huellas_codigo(raiz))
    codigo_ok = not any(cambios.values())

    archivo = buscar_mapeo_nuevo(raiz, mapeo)
    cfg, rf = _correr(raiz, archivo)
    motivos, checks = [], {}
    checks["codigo_y_config_sin_cambios"] = codigo_ok
    if not codigo_ok:
        motivos.append("Se modificó código o configuración congelada: " + json.dumps(cambios, ensure_ascii=False))

    if cfg is None:
        checks.update({"fuente_conectada": False, "todas_las_filas": False,
                       "bundles_validos": False, "coincide_esperado": False})
        motivos.append(f"El YAML no es válido: {rf}")
        resumen, comparacion, total_fuente = {}, None, None
    else:
        resumen = _resumen_fuente(rf)
        checks["fuente_conectada"] = rf.conectada
        if not rf.conectada:
            motivos.append(f"La fuente no se pudo conectar: {rf.error_configuracion}")
        try:
            total_fuente = contar_registros_independiente(cfg)
        except Exception as e:
            total_fuente = None
            motivos.append(f"No se pudo contar las filas de la fuente: {e}")
        checks["todas_las_filas"] = bool(rf.conectada and total_fuente and resumen["registros"] == total_fuente)
        if rf.conectada and not checks["todas_las_filas"]:
            motivos.append(f"Se procesaron {resumen['registros']} de {total_fuente} filas")
        checks["bundles_validos"] = bool(resumen.get("bundles_generados")) and \
            resumen["bundles_validos"] == resumen["bundles_generados"]
        if rf.conectada and not checks["bundles_validos"]:
            motivos.append(f"RDA válidos {resumen['bundles_validos']} de {resumen['bundles_generados']} generados")
        ruta_esp = Path(esperado) if esperado else raiz / "datos" / "fuentes" / "esperado_fuente4.csv"
        ruta_esp = ruta_esp if ruta_esp.is_absolute() else raiz / ruta_esp
        if ruta_esp.exists() and rf.conectada:
            comparacion = comparar_con_esperado(rf, leer_esperado(ruta_esp))
            comparacion["archivo"] = ruta_esp.name
            checks["coincide_esperado"] = comparacion["diferencias"] == 0 and comparacion["coinciden"] > 0
            if not checks["coincide_esperado"]:
                motivos.append(f"Lo normalizado no coincide con {ruta_esp.name} en "
                               f"{comparacion['diferencias']} caso(s)")
        else:
            comparacion = None
            checks["coincide_esperado"] = False
            if rf.conectada:
                motivos.append(f"No se encontró {ruta_esp.name}; no se pudo comparar lo normalizado")

    if not codigo_ok or not checks.get("fuente_conectada") or not resumen.get("registros"):
        veredicto = "no"
    elif all(checks.values()):
        veredicto = "si"
    else:
        veredicto = "parcial"

    resultado = {
        "veredicto": veredicto,
        "segundos": segundos,
        "minutos": round(segundos / 60, 1),
        "intentos": len(estado["intentos"]),
        "inicio": estado["inicio"],
        "fin": _ahora(),
        "verificaciones": checks,
        "motivos": motivos,
        "mapeo": {"archivo": archivo.name,
                  "sha256": sha256_archivo(archivo) if archivo.exists() else None,
                  "contenido": archivo.read_text(encoding="utf-8") if archivo.exists() else None},
        "fuente": {"archivo": cfg.ruta.name if cfg else None,
                   "filas_en_fuente": total_fuente,
                   "sha256_antes": rf.huella_antes if cfg else None,
                   "sha256_despues": rf.huella_despues if cfg else None,
                   "intacta": rf.intacta if cfg else None},
        "resumen_procesamiento": resumen,
        "comparacion_esperado": comparacion,
        "codigo_congelado": {"fecha": congelado["fecha"], "archivos": congelado["archivos"],
                             "git": congelado.get("git"), "cambios": cambios},
        "historial_intentos": estado["intentos"],
        "nota": "Tiempo = reloj del sistema entre 'inicio' y 'fin'. Compárese con el cronómetro manual.",
    }
    _escribir(r["resultado"], resultado)
    estado["terminado"] = True
    estado["fin"] = resultado["fin"]
    _escribir(r["estado"], estado)
    return resultado


# ---------------------------------------------------------------------
def _imprimir_intento(reg: dict) -> None:
    print(f"Intento {reg['numero']} · {reg['mapeo']} · {reg['segundos_desde_inicio'] / 60:.1f} min desde el inicio")
    if reg["resultado"] == "yaml_con_errores":
        print(f"  ✗ El YAML tiene problemas:\n  {reg['mensaje']}")
        return
    if reg["resultado"] == "no_conectada":
        print(f"  ✗ La fuente no se pudo conectar:\n  {reg['error_configuracion']}")
        return
    print(f"  ✓ Fuente conectada · registros {reg['registros']} · válidos {reg['validos']} · "
          f"con error {reg['con_error']} · RDA válidos {reg['bundles_validos']}/{reg['bundles_generados']}")
    if reg["columnas_ignoradas"]:
        print(f"  Columnas ignoradas: {', '.join(reg['columnas_ignoradas'])}")
    if reg["errores_por_tipo"]:
        print("  Errores por tipo: " + ", ".join(f"{k}={v}" for k, v in reg["errores_por_tipo"].items()))
        for e in reg["primeros_errores"]:
            print(f"    · {e}")


def main(argv=None) -> int:
    from saludia.consola import preparar_salida
    preparar_salida()
    ap = argparse.ArgumentParser(prog="c5_cronometro.py", description="Cronómetro del criterio C5")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("congelar", help="Guarda la huella SHA-256 del código y la configuración")
    pi = sub.add_parser("inicio", help="Arranca el cronómetro")
    pi.add_argument("--reiniciar", action="store_true", help="Descarta un cronómetro anterior en marcha")
    pt = sub.add_parser("intento", help="Prueba el YAML nuevo (solo la fuente nueva)")
    pt.add_argument("--mapeo", help="Ruta del YAML (si hay más de uno nuevo)")
    sub.add_parser("estado", help="Muestra cómo va el cronómetro")
    pf = sub.add_parser("fin", help="Detiene el cronómetro, verifica y da el veredicto")
    pf.add_argument("--mapeo")
    pf.add_argument("--esperado", help="CSV esperado (por defecto datos/fuentes/esperado_fuente4.csv)")
    a = ap.parse_args(argv)

    if a.cmd == "congelar":
        d = congelar()
        print(f"Código congelado · {d['archivos']} archivos · {d['fecha']}")
        for k, v in d["huellas"].items():
            print(f"  {v[:16]}…  {k}")
        if d["git"].get("commit"):
            print(f"  git: {d['git']['commit']}" + (" (con cambios sin commit)" if d["git"]["cambios_sin_commit"] else ""))
    elif a.cmd == "inicio":
        e = inicio(reiniciar=a.reiniciar)
        print(f"⏱  Cronómetro iniciado: {e['inicio']}. Inicia también tu cronómetro manual.")
    elif a.cmd == "intento":
        _imprimir_intento(intento(mapeo=a.mapeo))
    elif a.cmd == "estado":
        r = _rutas(RAIZ)
        e = _leer(r["estado"])
        if not e:
            print("No se ha iniciado el cronómetro.")
        else:
            fin_txt = e.get("fin") or "en marcha"
            transcurrido = (time.time() - e["inicio_epoch"]) / 60
            print(f"Inicio: {e['inicio']} · estado: {fin_txt} · intentos: {len(e['intentos'])}"
                  + ("" if e.get("terminado") else f" · {transcurrido:.1f} min transcurridos"))
    elif a.cmd == "fin":
        res = fin(mapeo=a.mapeo, esperado=a.esperado)
        simbolo = {"si": "✓", "parcial": "◐", "no": "✗"}[res["veredicto"]]
        print(f"{simbolo} C5 · veredicto: {res['veredicto'].upper()} · tiempo {res['minutos']} min "
              f"({res['segundos']} s) · intentos {res['intentos']}")
        for k, v in res["verificaciones"].items():
            print(f"  {'✓' if v else '✗'} {k}")
        for m in res["motivos"]:
            print(f"  · {m}")
        print("Resultado guardado en salidas/c5.json. Corre 'python main.py ejecutar' para actualizar métricas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
