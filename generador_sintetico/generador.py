"""Generador de datos sintéticos de SALUDIA.

Produce 300 atenciones de consulta externa (100 por fuente) con Faker
(locale es_CO) y una semilla fija, y siembra exactamente 30 errores
(un error por registro) cuya lista de verdad queda en
datos/errores_sembrados.csv.

Este paquete NO es parte del conector: el conector nunca lo importa y
nunca lee errores_sembrados.csv. Solo el módulo de métricas lo usa para
calcular C3.

Ningún dato corresponde a personas reales.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from faker import Faker
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

RAIZ = Path(__file__).resolve().parent.parent

FUENTE1 = "fuente1_sqlite"
FUENTE2 = "fuente2_csv"
FUENTE3 = "fuente3_excel"

ARCHIVOS = {
    FUENTE1: "fuente1_his_clinico.sqlite",
    FUENTE2: "fuente2_exportacion_antigua.csv",
    FUENTE3: "fuente3_registro_manual.xlsx",
}

CAMPOS_OBLIGATORIOS = [
    "id_atencion", "tipo_documento", "numero_documento", "sexo",
    "fecha_nacimiento", "fecha_atencion", "codigo_cie10",
]

# ---------------------------------------------------------------------
# Disposición de cada fuente (solo la usa el generador para escribir
# los archivos; el conector la descubre a través de los YAML de mapeo).
# ---------------------------------------------------------------------
COLUMNAS = {
    FUENTE1: {  # software clínico tradicional: nombres abreviados
        "id_atencion": "id_aten", "tipo_documento": "tip_doc",
        "numero_documento": "num_doc", "nombres": "nom_pac",
        "apellidos": "ape_pac", "sexo": "sexo",
        "fecha_nacimiento": "fec_nac", "fecha_atencion": "fec_consulta",
        "codigo_cie10": "cod_dx",
    },
    FUENTE2: {  # exportación de software antiguo: PascalCase
        "id_atencion": "IdAtencion", "tipo_documento": "TipoID",
        "numero_documento": "NumeroID", "nombres": "Nombres",
        "apellidos": "Apellidos", "sexo": "Sexo",
        "fecha_nacimiento": "FechaNacimiento", "fecha_atencion": "FechaAtencion",
        "codigo_cie10": "CodDiagnostico",
    },
    FUENTE3: {  # hoja diligenciada a mano: encabezados en lenguaje natural
        "id_atencion": "N° atención", "tipo_documento": "Tipo de documento",
        "numero_documento": "No. documento", "nombres": "Nombres",
        "apellidos": "Apellidos", "sexo": "Género",
        "fecha_nacimiento": "F. nacimiento", "fecha_atencion": "Fecha consulta",
        "codigo_cie10": "Dx principal (CIE-10)",
    },
}

FORMATO_FECHA = {
    FUENTE1: {"fecha_nacimiento": "%Y-%m-%d", "fecha_atencion": "%Y-%m-%d %H:%M"},
    FUENTE2: {"fecha_nacimiento": "%d/%m/%Y", "fecha_atencion": "%d/%m/%Y"},
    FUENTE3: {"fecha_nacimiento": "%d-%m-%Y", "fecha_atencion": "%d-%m-%Y"},
}

SEXO = {
    FUENTE1: {"M": "M", "F": "F"},
    FUENTE2: {"M": "1", "F": "2"},
    FUENTE3: {"M": "Masculino", "F": "Femenino"},
}

TIPO_DOC = {
    FUENTE1: {"CC": "CC", "TI": "TI", "RC": "RC", "CE": "CE", "PA": "PA"},
    FUENTE2: {"CC": "1", "TI": "2", "RC": "3", "CE": "4", "PA": "5"},
    FUENTE3: {
        "CC": "Cédula de ciudadanía", "TI": "Tarjeta de identidad",
        "RC": "Registro civil", "CE": "Cédula de extranjería", "PA": "Pasaporte",
    },
}

# Fila de encabezados en Excel (las filas 1 a 3 tienen título y notas).
EXCEL_FILA_ENCABEZADO = 4

# ---------------------------------------------------------------------
# Valores erróneos sembrados (uno por registro afectado).
# Ninguno de estos códigos existe en la CIE-10; se comprueba contra el
# catálogo al generar.
# ---------------------------------------------------------------------
CIE10_INEXISTENTES = {
    FUENTE1: ["K999", "E999", "J0O9", "H999"],     # J0O9: letra O en vez de cero
    FUENTE2: ["D999", "P999", "I1OX"],              # I1OX: letra O en vez de cero
    FUENTE3: ["C999", "Ñ100", "J4S9"],              # errores de teclado
}

FECHAS_INVALIDAS = {
    # (campo, valor) — imposibles o con un formato distinto al declarado
    FUENTE1: [
        ("fecha_atencion", "2026-02-30 09:15"),     # 30 de febrero
        ("fecha_nacimiento", "1985-02-29"),         # 1985 no es bisiesto
        ("fecha_atencion", "04/03/2026 08:30"),     # formato de otra fuente
    ],
    FUENTE2: [
        ("fecha_atencion", "31/02/2026"),           # 31 de febrero
        ("fecha_nacimiento", "12/14/1990"),         # mes 14
        ("fecha_atencion", "2026-03-15"),           # formato ISO, no DD/MM/AAAA
        ("fecha_nacimiento", "15-07-1978"),         # guiones en vez de barras
    ],
    FUENTE3: [
        ("fecha_atencion", "31-04-2026"),           # abril tiene 30 días
        ("fecha_nacimiento", "29-02-2025"),         # 2025 no es bisiesto
        ("fecha_atencion", "15/03/2026"),           # barras en vez de guiones
    ],
}

# Rotación de campos vacíos entre los 7 obligatorios (10 en total).
VACIOS = {
    FUENTE1: ["tipo_documento", "numero_documento", "sexo"],
    FUENTE2: ["fecha_nacimiento", "fecha_atencion", "codigo_cie10"],
    FUENTE3: ["id_atencion", "numero_documento", "codigo_cie10", "sexo"],
}

# Cómo se ve "vacío" en cada fuente
def _valor_vacio(fuente: str, n: int):
    if fuente == FUENTE1:
        return None                 # NULL en SQLite
    if fuente == FUENTE2:
        return "   " if n == 1 else ""  # una celda solo con espacios
    return None                     # celda vacía en Excel


# Restricciones clínicas mínimas para que los datos "normales" sean
# plausibles: código -> (sexo o None, edad mínima, edad máxima)
RESTRICCIONES = {
    "B373": ("F", 12, 90), "C539": ("F", 30, 90), "D259": ("F", 25, 70),
    "N72X": ("F", 15, 80), "N760": ("F", 12, 90), "N912": ("F", 15, 45),
    "N920": ("F", 12, 52), "N943": ("F", 13, 50), "N946": ("F", 12, 50),
    "N951": ("F", 42, 65), "Z014": ("F", 15, 90), "Z124": ("F", 25, 70),
    "Z321": ("F", 16, 44), "Z348": ("F", 16, 44), "Z392": ("F", 16, 44),
    "Z304": ("F", 15, 49), "C509": ("F", 30, 90), "Z123": ("F", 40, 75),
    "C61X": ("M", 50, 95), "N40X": ("M", 45, 95), "N410": ("M", 20, 90),
    "Z125": ("M", 45, 80),
    "Z001": (None, 0, 11), "Z003": (None, 10, 19), "F900": (None, 5, 17),
    "J210": (None, 0, 2), "J219": (None, 0, 2), "J050": (None, 0, 6),
    "A080": (None, 0, 5), "J352": (None, 1, 14), "B850": (None, 3, 60),
    "I10X": (None, 30, 95), "I119": (None, 40, 95), "I209": (None, 40, 95),
    "I251": (None, 45, 95), "I500": (None, 50, 95), "I509": (None, 50, 95),
    "I639": (None, 50, 95), "E119": (None, 30, 95), "E117": (None, 40, 95),
    "E149": (None, 30, 95), "E780": (None, 25, 95), "E781": (None, 25, 95),
    "E782": (None, 25, 95), "E785": (None, 25, 95), "M179": (None, 40, 95),
    "M159": (None, 45, 95), "M199": (None, 40, 95), "M819": (None, 45, 95),
    "H269": (None, 50, 95), "H409": (None, 40, 95), "H524": (None, 40, 95),
    "J449": (None, 45, 95), "N189": (None, 40, 95), "C169": (None, 40, 95),
    "C189": (None, 40, 95), "G473": (None, 25, 90), "F100": (None, 18, 80),
    "F172": (None, 18, 85), "F200": (None, 18, 70), "F319": (None, 18, 80),
    "A539": (None, 16, 80), "A549": (None, 16, 70), "A560": (None, 16, 60),
    "A599": (None, 16, 70), "A600": (None, 16, 70), "A630": (None, 16, 70),
    "B24X": (None, 16, 80), "L700": (None, 12, 35), "L709": (None, 12, 35),
    "Z300": (None, 15, 49), "M797": (None, 25, 80), "N393": (None, 35, 90),
    "K021": (None, 3, 90), "K029": (None, 3, 90), "Z012": (None, 2, 90),
}

# Códigos frecuentes en consulta externa (pedidos por el equipo):
# se eligen con más probabilidad.
FRECUENTES = [
    "A099", "E039", "F419", "G439", "H109", "I10X", "J00X", "J039", "J459",
    "K297", "M255", "M545", "N390", "N760", "R104", "R51X",
]

OBSERVACIONES = [
    "", "", "", "Control en 1 mes", "Se entrega fórmula", "Remitido a laboratorio",
    "Paciente refiere mejoría", "Cita de control", "Se dan recomendaciones",
]
USUARIOS = ["recepcion01", "recepcion02", "facturacion", "auxadmin"]


@dataclass
class Atencion:
    """Atención 'verdadera' antes de escribirla en el formato de cada fuente."""
    id_atencion: str
    tipo_documento: str
    numero_documento: str
    nombres: str
    apellidos: str
    sexo: str                # M / F
    fecha_nacimiento: date
    fecha_atencion: datetime
    codigo_cie10: str
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------
def cargar_parametros() -> dict:
    with open(RAIZ / "config" / "parametros.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cargar_codigos_catalogo(ruta: Path) -> list[str]:
    with open(ruta, encoding="utf-8", newline="") as f:
        return [fila["Codigo"].strip() for fila in csv.DictReader(f, delimiter=";")]


def _edad(nac: date, ref: date) -> int:
    return ref.year - nac.year - ((ref.month, ref.day) < (nac.month, nac.day))


def _sortear_edad(rng: random.Random) -> int:
    grupos = [((0, 4), 10), ((5, 14), 12), ((15, 29), 20), ((30, 49), 25),
              ((50, 69), 22), ((70, 90), 11)]
    (lo, hi), = rng.choices([g for g, _ in grupos], weights=[w for _, w in grupos])
    return rng.randint(lo, hi)


def _tipo_y_numero(rng: random.Random, edad: int) -> tuple[str, str]:
    if edad < 7:
        return "RC", str(rng.randint(1_000_000_000, 1_199_999_999))
    if edad < 18:
        return "TI", str(rng.randint(1_000_000_000, 1_149_999_999))
    tipo = rng.choices(["CC", "CE", "PA"], weights=[92, 5, 3])[0]
    if tipo == "CC":
        return tipo, str(rng.randint(3_000_000, 1_150_000_000))
    if tipo == "CE":
        return tipo, str(rng.randint(100_000, 9_999_999))
    letras = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(2))
    return tipo, f"{letras}{rng.randint(1_000_000, 9_999_999)}"


def _sortear_codigo(rng: random.Random, codigos: list[str], sexo: str, edad: int) -> str:
    pesos = [6 if c in FRECUENTES else 1 for c in codigos]
    while True:
        c = rng.choices(codigos, weights=pesos)[0]
        sx, emin, emax = RESTRICCIONES.get(c, (None, 0, 120))
        if (sx is None or sx == sexo) and emin <= edad <= emax:
            return c


def _sortear_fecha_atencion(rng: random.Random, desde: date, hasta: date) -> datetime:
    while True:
        d = desde + timedelta(days=rng.randint(0, (hasta - desde).days))
        if d.weekday() < 6:  # lunes a sábado
            break
    hora = rng.randint(7, 17)
    minuto = rng.choice(range(0, 60, 5))
    return datetime(d.year, d.month, d.day, hora, minuto)


def generar_atenciones(fake: Faker, rng: random.Random, n: int, codigos: list[str],
                       desde: date, hasta: date) -> list[Atencion]:
    crudas = []
    for _ in range(n):
        sexo = rng.choice(["M", "F"])
        f_aten = _sortear_fecha_atencion(rng, desde, hasta)
        edad = _sortear_edad(rng)
        nac = f_aten.date() - timedelta(days=edad * 365 + rng.randint(0, 364))
        edad_real = _edad(nac, f_aten.date())
        tipo, numero = _tipo_y_numero(rng, edad_real)
        if sexo == "M":
            nombres = fake.first_name_male()
            if rng.random() < 0.5:
                nombres += " " + fake.first_name_male()
        else:
            nombres = fake.first_name_female()
            if rng.random() < 0.5:
                nombres += " " + fake.first_name_female()
        apellidos = f"{fake.last_name()} {fake.last_name()}"
        crudas.append(Atencion(
            id_atencion="", tipo_documento=tipo, numero_documento=numero,
            nombres=nombres, apellidos=apellidos, sexo=sexo,
            fecha_nacimiento=nac, fecha_atencion=f_aten,
            codigo_cie10=_sortear_codigo(rng, codigos, sexo, edad_real),
            extra={"usuario": rng.choice(USUARIOS),
                   "observacion": rng.choice(OBSERVACIONES)},
        ))
    crudas.sort(key=lambda a: a.fecha_atencion)
    return crudas


# ---------------------------------------------------------------------
# Conversión al formato de cada fuente
# ---------------------------------------------------------------------
def _id_fuente(fuente: str, i: int):
    if fuente == FUENTE1:
        return 70001 + i                 # entero, estilo consecutivo de HIS
    if fuente == FUENTE2:
        return f"AT2026-{1001 + i:04d}"
    return i + 1                         # Excel: número de fila escrito a mano


def a_formato_fuente(fuente: str, a: Atencion) -> dict:
    """Devuelve {campo_comun: valor_en_formato_de_la_fuente}."""
    fmt = FORMATO_FECHA[fuente]
    return {
        "id_atencion": a.id_atencion,
        "tipo_documento": TIPO_DOC[fuente][a.tipo_documento],
        "numero_documento": a.numero_documento,
        "nombres": a.nombres,
        "apellidos": a.apellidos,
        "sexo": SEXO[fuente][a.sexo],
        "fecha_nacimiento": a.fecha_nacimiento.strftime(fmt["fecha_nacimiento"]),
        "fecha_atencion": a.fecha_atencion.strftime(fmt["fecha_atencion"]),
        "codigo_cie10": a.codigo_cie10,
    }


def fila_en_archivo(fuente: str, i: int) -> int:
    """Número de fila tal como lo vería una persona al abrir el archivo."""
    if fuente == FUENTE1:
        return i + 1                     # rowid de SQLite
    if fuente == FUENTE2:
        return i + 2                     # línea 1 = encabezado
    return EXCEL_FILA_ENCABEZADO + 1 + i  # fila de Excel


# ---------------------------------------------------------------------
# Siembra de errores
# ---------------------------------------------------------------------
def sembrar_errores(fuente: str, registros: list[dict], ids: list, cantidades: dict,
                    rng: random.Random, catalogo: set[str]) -> list[dict]:
    total = sum(cantidades.values())
    posiciones = sorted(rng.sample(range(len(registros)), total))
    rng.shuffle(posiciones)
    plan = (["cie10_inexistente"] * cantidades["cie10_inexistente"]
            + ["fecha_invalida"] * cantidades["fecha_invalida"]
            + ["campo_obligatorio_vacio"] * cantidades["campo_obligatorio_vacio"])
    assert len(CIE10_INEXISTENTES[fuente]) == cantidades["cie10_inexistente"]
    assert len(FECHAS_INVALIDAS[fuente]) == cantidades["fecha_invalida"]
    assert len(VACIOS[fuente]) == cantidades["campo_obligatorio_vacio"]

    cola_cie = list(CIE10_INEXISTENTES[fuente])
    cola_fecha = list(FECHAS_INVALIDAS[fuente])
    cola_vacio = list(VACIOS[fuente])
    verdad = []
    n_vacio = 0
    for pos, tipo in zip(posiciones, plan):
        reg = registros[pos]
        if tipo == "cie10_inexistente":
            campo, valor = "codigo_cie10", cola_cie.pop(0)
            assert valor not in catalogo, f"{valor} no debe existir en el catálogo"
        elif tipo == "fecha_invalida":
            campo, valor = cola_fecha.pop(0)
        else:
            campo = cola_vacio.pop(0)
            valor = _valor_vacio(fuente, n_vacio)
            n_vacio += 1
        reg[campo] = valor
        id_en_fuente = reg["id_atencion"]
        verdad.append({
            "fuente": fuente,
            "id_atencion": "" if id_en_fuente in (None, "") else str(id_en_fuente),
            "fila": fila_en_archivo(fuente, pos),
            "campo": campo,
            "tipo_error": tipo,
            "valor": "" if valor is None else str(valor),
            # Para el cruce cuando el id está vacío: id original del registro
            "id_original": str(ids[pos]),
        })
    verdad.sort(key=lambda v: v["fila"])
    return verdad


# ---------------------------------------------------------------------
# Escritura de archivos
# ---------------------------------------------------------------------
def escribir_sqlite(ruta: Path, registros: list[dict], extras: list[dict]) -> None:
    ruta.unlink(missing_ok=True)
    cols = COLUMNAS[FUENTE1]
    con = sqlite3.connect(ruta)
    try:
        con.execute("""
            CREATE TABLE tb_usuarios (
                usr_cod TEXT PRIMARY KEY, usr_nombre TEXT, usr_rol TEXT)""")
        con.executemany("INSERT INTO tb_usuarios VALUES (?,?,?)", [
            ("recepcion01", "Recepción turno mañana", "ADMIN"),
            ("recepcion02", "Recepción turno tarde", "ADMIN"),
            ("facturacion", "Facturación", "ADMIN"),
            ("auxadmin", "Auxiliar administrativo", "ADMIN"),
        ])
        con.execute(f"""
            CREATE TABLE tb_atencion (
                {cols['id_atencion']} INTEGER,
                {cols['tipo_documento']} TEXT,
                {cols['numero_documento']} TEXT,
                {cols['nombres']} TEXT,
                {cols['apellidos']} TEXT,
                {cols['sexo']} TEXT,
                {cols['fecha_nacimiento']} TEXT,
                {cols['fecha_atencion']} TEXT,
                {cols['codigo_cie10']} TEXT,
                usr_reg TEXT,
                est_reg TEXT
            )""")
        orden = list(cols.keys())
        filas = [tuple(r[c] for c in orden) + (e["usuario"], "A")
                 for r, e in zip(registros, extras)]
        con.executemany(f"INSERT INTO tb_atencion VALUES ({','.join('?' * 11)})", filas)
        con.commit()
    finally:
        con.close()


def escribir_csv(ruta: Path, registros: list[dict], extras: list[dict]) -> None:
    cols = COLUMNAS[FUENTE2]
    encabezado = list(cols.values()) + ["CodPrestador", "Usuario"]
    # Windows-1252 y fin de línea CRLF: típico de un software de escritorio antiguo
    with open(ruta, "w", encoding="cp1252", newline="") as f:
        w = csv.writer(f, delimiter=",", lineterminator="\r\n")
        w.writerow(encabezado)
        for r, e in zip(registros, extras):
            w.writerow([("" if r[c] is None else r[c]) for c in cols]
                       + ["SINTETICO-0001", e["usuario"].upper()])


def escribir_excel(ruta: Path, registros: list[dict], extras: list[dict], ips: str) -> None:
    cols = COLUMNAS[FUENTE3]
    wb = Workbook()
    ws = wb.active
    ws.title = "Atenciones"
    encabezado = list(cols.values()) + ["Observaciones"]
    ncol = len(encabezado)
    ws.cell(row=1, column=1, value="REGISTRO DIARIO DE ATENCIONES – CONSULTA EXTERNA")
    ws.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    ws.cell(row=2, column=1,
            value=f"{ips} · Datos sintéticos para prototipo académico · No son pacientes reales")
    ws.cell(row=2, column=1).font = Font(italic=True, size=9, color="666666")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncol)
    # fila 3 en blanco, como suelen quedar las hojas hechas a mano
    borde = Border(*(Side(style="thin", color="999999"),) * 4)
    for j, nombre in enumerate(encabezado, start=1):
        c = ws.cell(row=EXCEL_FILA_ENCABEZADO, column=j, value=nombre)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDEBF7")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = borde
    for i, (r, e) in enumerate(zip(registros, extras)):
        fila = EXCEL_FILA_ENCABEZADO + 1 + i
        valores = [r[c] for c in cols] + [e["observacion"] or None]
        for j, v in enumerate(valores, start=1):
            c = ws.cell(row=fila, column=j, value=v)
            c.border = borde
            # Las fechas y el documento se escriben como TEXTO, como lo
            # haría una persona que digita en la hoja
            if j > 1 and v is not None:
                c.number_format = "@"
    anchos = [11, 22, 16, 22, 24, 12, 14, 14, 13, 26]
    for j, a in enumerate(anchos, start=1):
        ws.column_dimensions[ws.cell(row=EXCEL_FILA_ENCABEZADO, column=j).column_letter].width = a
    ws.freeze_panes = ws.cell(row=EXCEL_FILA_ENCABEZADO + 1, column=1)
    fijo = datetime(2026, 11, 22, 8, 0, 0)
    wb.properties.creator = "Generador sintético SALUDIA"
    wb.properties.created = fijo
    wb.properties.modified = fijo
    wb.save(ruta)


def escribir_verdad(ruta: Path, verdad: list[dict]) -> None:
    campos = ["fuente", "id_atencion", "fila", "campo", "tipo_error", "valor", "id_original"]
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(verdad)


def _huella(fuente: str, ruta: Path) -> str:
    from .verificar import huella_contenido  # import local: evita ciclo
    return huella_contenido(fuente, ruta)


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()


# ---------------------------------------------------------------------
def generar(semilla: int | None = None, raiz: Path = RAIZ) -> dict:
    p = cargar_parametros()
    ds = p["datos_sinteticos"]
    semilla = ds["semilla"] if semilla is None else semilla
    rutas = p["rutas"]
    dir_fuentes = raiz / rutas["fuentes"]
    dir_fuentes.mkdir(parents=True, exist_ok=True)

    codigos = cargar_codigos_catalogo(raiz / rutas["referencia_cie10_subconjunto"])
    catalogo = set(codigos)
    faltan = [c for c in FRECUENTES if c not in catalogo]
    assert not faltan, f"Faltan códigos frecuentes en el catálogo: {faltan}"

    rng = random.Random(semilla)
    fake = Faker(ds["locale"])
    fake.seed_instance(semilla)
    desde = date.fromisoformat(ds["fecha_atencion_desde"])
    hasta = date.fromisoformat(ds["fecha_atencion_hasta"])
    n = ds["atenciones_por_fuente"]

    verdad_total, resumen = [], {}
    for fuente in (FUENTE1, FUENTE2, FUENTE3):
        atenciones = generar_atenciones(fake, rng, n, codigos, desde, hasta)
        ids = []
        for i, a in enumerate(atenciones):
            a.id_atencion = _id_fuente(fuente, i)
            ids.append(a.id_atencion)
        registros = [a_formato_fuente(fuente, a) for a in atenciones]
        extras = [a.extra for a in atenciones]
        verdad = sembrar_errores(fuente, registros, ids, ds["errores"][fuente], rng, catalogo)
        verdad_total.extend(verdad)

        ruta = dir_fuentes / ARCHIVOS[fuente]
        if fuente == FUENTE1:
            escribir_sqlite(ruta, registros, extras)
        elif fuente == FUENTE2:
            escribir_csv(ruta, registros, extras)
        else:
            escribir_excel(ruta, registros, extras, p["ips_simulada"]["nombre"])
        resumen[fuente] = {"archivo": str(ruta.relative_to(raiz)), "registros": n,
                           "errores_sembrados": len(verdad)}

    ruta_verdad = raiz / rutas["errores_sembrados"]
    escribir_verdad(ruta_verdad, verdad_total)

    manifiesto = {
        "semilla": semilla,
        "locale": ds["locale"],
        "total_atenciones": n * 3,
        "total_errores_sembrados": len(verdad_total),
        "fuentes": resumen,
        "sha256_archivo": {f: sha256(raiz / r["archivo"]) for f, r in resumen.items()},
        "sha256_contenido": {f: _huella(f, raiz / r["archivo"]) for f, r in resumen.items()},
        "sha256_errores_sembrados": sha256(ruta_verdad),
        "nota": "Datos 100 % sintéticos. No corresponden a personas reales.",
    }
    with open(raiz / "datos" / "manifiesto_datos.json", "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)
    return manifiesto
