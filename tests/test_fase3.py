"""Pruebas de adaptadores, mapeo YAML, modelo común, normalizador y validador."""
import builtins
import csv
import shutil
import sqlite3
import tempfile
import textwrap
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from openpyxl import Workbook

from generador_sintetico import generador as g
from saludia import adaptadores
from saludia.catalogo import cargar_catalogo
from saludia.conector import extraer_atenciones
from saludia.integridad import huellas
from saludia.mapeo import cargar_mapeo, descubrir_mapeos
from saludia.modelo import (CAMPO_VACIO, CIE10_INEXISTENTE, FECHA_INVALIDA, AtencionComun,
                            ErrorConfiguracion, RegistroCrudo, VALOR_NO_RECONOCIDO)
from saludia.normalizador import mapear, normalizar
from saludia.validador import validar

RAIZ = Path(__file__).resolve().parent.parent
CAT_OFICIAL = "datos/referencia/cie10_sispro.csv"
CAT_SUB = "datos/referencia/cie10_subconjunto.csv"


def catalogo():
    return cargar_catalogo(RAIZ, CAT_OFICIAL, CAT_SUB)


def configs():
    return {c.id: c for c in (cargar_mapeo(m, RAIZ) for m in descubrir_mapeos(RAIZ / "mapeos"))}


def rutas_fuentes():
    return {k: RAIZ / "datos" / "fuentes" / v for k, v in g.ARCHIVOS.items()}


class TestLecturaFuentes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        g.generar()
        cls.cat = catalogo()
        cls.res = {fid: extraer_atenciones(cfg, cls.cat) for fid, cfg in configs().items()}

    def test_parseo_de_las_tres_fuentes(self):
        for fid in (g.FUENTE1, g.FUENTE2, g.FUENTE3):
            lectura, ats = self.res[fid]
            self.assertEqual(len(lectura.registros), 100, fid)
            validos = [a for a in ats if a.valida]
            self.assertEqual(len(validos), 90, fid)
            for a in validos:
                self.assertIn(a.sexo, ("M", "F"))
                self.assertIn(a.tipo_documento, ("CC", "TI", "RC", "CE", "PA"))
                self.assertIsInstance(a.fecha_nacimiento, date)
                self.assertIsInstance(a.fecha_atencion, (date, datetime))
                self.assertIn(a.codigo_cie10, self.cat)

    def test_columnas_no_mapeadas_se_ignoran(self):
        self.assertEqual(self.res[g.FUENTE1][0].columnas_ignoradas, ["usr_reg", "est_reg"])
        self.assertEqual(self.res[g.FUENTE2][0].columnas_ignoradas, ["CodPrestador", "Usuario"])
        self.assertEqual(self.res[g.FUENTE3][0].columnas_ignoradas, ["Observaciones"])

    def test_mismo_registro_queda_igual_en_las_tres_representaciones(self):
        # el primer registro normal de cada fuente queda con tipos estándar
        for fid in (g.FUENTE1, g.FUENTE2, g.FUENTE3):
            a = next(x for x in self.res[fid][1] if x.valida)
            self.assertRegex(a.fecha_nacimiento.isoformat(), r"^\d{4}-\d{2}-\d{2}$")


class TestReglaSoloLectura(unittest.TestCase):
    """Regla 1: la fuente se abre en solo lectura."""

    def test_sqlite_rechaza_escritura(self):
        con = adaptadores.abrir_sqlite_solo_lectura(rutas_fuentes()[g.FUENTE1])
        try:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("UPDATE tb_atencion SET sexo = 'X'")
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("CREATE TABLE intruso (a)")
        finally:
            con.close()

    def test_csv_y_excel_se_abren_sin_modo_escritura(self):
        modos = []
        abrir_real = builtins.open

        def espia(archivo, modo="r", *a, **k):
            modos.append((str(archivo), modo))
            return abrir_real(archivo, modo, *a, **k)

        cfgs = configs()
        with mock.patch("builtins.open", espia):
            adaptadores.leer_fuente(cfgs[g.FUENTE2])
            adaptadores.leer_fuente(cfgs[g.FUENTE3])
        fuentes = [m for (r, m) in modos if "datos" in r and "fuentes" in r]
        self.assertTrue(fuentes)
        for m in fuentes:
            self.assertFalse(set(m) & set("wax+"), f"modo de escritura: {m}")

    def test_huella_sha256_igual_antes_y_despues(self):
        antes = huellas(rutas_fuentes())
        cat = catalogo()
        for cfg in configs().values():
            extraer_atenciones(cfg, cat)
        self.assertEqual(antes, huellas(rutas_fuentes()))


class TestReglaErroresSeReportan(unittest.TestCase):
    """Regla 3: los registros con error se reportan; no se borran ni se corrigen."""

    def test_ningun_registro_desaparece_y_el_valor_original_se_conserva(self):
        g.generar()
        cat = catalogo()
        with open(RAIZ / "datos" / "errores_sembrados.csv", encoding="utf-8") as f:
            verdad = {(v["fuente"], int(v["fila"])): v for v in csv.DictReader(f)}
        for cfg in configs().values():
            lectura, ats = extraer_atenciones(cfg, cat)
            self.assertEqual(len(ats), len(lectura.registros))
            for a in ats:
                v = verdad.get((a.fuente, a.fila))
                if v is None or v["tipo_error"] == CAMPO_VACIO:
                    continue
                self.assertFalse(a.valida)
                # el valor erróneo se conserva tal cual (no se corrige)
                self.assertEqual(str(a.crudo[v["campo"]]).strip(), v["valor"].strip())
                if v["tipo_error"] == FECHA_INVALIDA:
                    self.assertIsNone(getattr(a, v["campo"]))        # no se adivina la fecha
                else:
                    self.assertEqual(getattr(a, v["campo"]), v["valor"])  # el código no se corrige


class TestReglaSinExcepciones(unittest.TestCase):
    """Regla 4: normalizador y validador no lanzan excepciones por datos malos."""

    BASURA = [None, "", "   ", "\x00\x01", "😀" * 50, "x" * 10_000, 12345, -1.5, float("nan"),
              b"\xff\xfe", ["lista"], {"a": 1}, object(), True, datetime(2026, 1, 1), date(1990, 1, 1),
              "31/02/2026", "9999-99-99", "NULL", "DROP TABLE x;"]

    def test_basura_en_todos_los_campos(self):
        cat = catalogo()
        for cfg in configs().values():
            usadas = cfg.columnas
            for valor in self.BASURA:
                reg = RegistroCrudo(cfg.id, 1, {col: valor for col in usadas.values()})
                try:
                    at = validar(normalizar(mapear(reg, cfg, usadas), cfg), cat)
                except Exception as e:  # pragma: no cover
                    self.fail(f"{cfg.id} lanzó {type(e).__name__} con {valor!r}: {e}")
                self.assertIsInstance(at, AtencionComun)

    def test_csv_con_filas_mal_formadas_no_detiene_la_lectura(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "f.csv").write_text(
                "id,td,nd,sx,fn,fa,dx\n"
                "1,CC,10,M,01/01/1990,02/02/2026,J00X\n"
                "2,CC,11,F,01/01/1991\n"                      # incompleta
                "3,CC,12,F,01/01/1992,02/02/2026,J00X,extra\n"  # campo de más
                "\n"
                "4,CC,13,M,01/01/1993,02/02/2026,R51X\n", encoding="utf-8")
            (tmp / "m.yaml").write_text(textwrap.dedent("""
                version_esquema: 1
                fuente: {id: prueba, tipo: csv, ruta: f.csv}
                columnas: {id_atencion: id, tipo_documento: td, numero_documento: nd, sexo: sx,
                           fecha_nacimiento: fn, fecha_atencion: fa, codigo_cie10: dx}
                formatos_fecha: {fecha_nacimiento: "%d/%m/%Y", fecha_atencion: "%d/%m/%Y"}
                """), encoding="utf-8")
            cfg = cargar_mapeo(tmp / "m.yaml", tmp)
            lectura, ats = extraer_atenciones(cfg, catalogo())
            self.assertEqual([a.fila for a in ats], [2, 3, 4, 6])
            self.assertEqual([a.valida for a in ats], [True, False, False, True])


class TestUnCasoPorTipoDeError(unittest.TestCase):
    def setUp(self):
        self.cfg = configs()[g.FUENTE2]
        self.cat = catalogo()
        self.base = {"IdAtencion": "AT-1", "TipoID": "1", "NumeroID": "123", "Nombres": "Ana",
                     "Apellidos": "Ruiz", "Sexo": "2", "FechaNacimiento": "01/02/1990",
                     "FechaAtencion": "03/04/2026", "CodDiagnostico": "J00X"}

    def _procesar(self, **cambios):
        datos = dict(self.base, **cambios)
        reg = RegistroCrudo(self.cfg.id, 2, datos)
        return validar(normalizar(mapear(reg, self.cfg, self.cfg.columnas), self.cfg), self.cat)

    def test_registro_normal_valido(self):
        self.assertTrue(self._procesar().valida)

    def test_cie10_inexistente(self):
        at = self._procesar(CodDiagnostico="K999")
        self.assertEqual([(h.campo, h.tipo_error) for h in at.hallazgos],
                         [("codigo_cie10", CIE10_INEXISTENTE)])

    def test_fecha_imposible(self):
        at = self._procesar(FechaAtencion="31/02/2026")
        self.assertEqual([(h.campo, h.tipo_error) for h in at.hallazgos],
                         [("fecha_atencion", FECHA_INVALIDA)])
        self.assertIn("calendario", at.hallazgos[0].mensaje)

    def test_fecha_mal_formateada(self):
        at = self._procesar(FechaNacimiento="1990-02-01")
        self.assertEqual(at.hallazgos[0].tipo_error, FECHA_INVALIDA)
        self.assertIn("formato", at.hallazgos[0].mensaje)

    def test_campo_obligatorio_vacio_y_solo_espacios(self):
        for valor in ("", "   ", None):
            at = self._procesar(NumeroID=valor)
            self.assertEqual([(h.campo, h.tipo_error) for h in at.hallazgos],
                             [("numero_documento", CAMPO_VACIO)])

    def test_codigo_no_reconocido(self):
        at = self._procesar(Sexo="9")
        self.assertEqual(at.hallazgos[0].tipo_error, VALOR_NO_RECONOCIDO)

    def test_nacimiento_posterior_a_la_atencion(self):
        at = self._procesar(FechaNacimiento="01/01/2026", FechaAtencion="01/01/2025")
        self.assertEqual(at.hallazgos[0].tipo_error, "fecha_incoherente")


class TestCatalogoSispro(unittest.TestCase):
    """Regla 5: el catálogo CIE-10 sale de la tabla de referencia de SISPRO."""

    def test_usa_subconjunto_si_no_hay_tabla_oficial(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "datos/referencia").mkdir(parents=True)
            shutil.copy(RAIZ / CAT_SUB, tmp / CAT_SUB)
            cat = cargar_catalogo(tmp, CAT_OFICIAL, CAT_SUB)
            self.assertIn("subconjunto", cat.origen)
            self.assertEqual(len(cat), 300)

    def test_prefiere_tabla_oficial_y_respeta_habilitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "datos/referencia").mkdir(parents=True)
            shutil.copy(RAIZ / CAT_SUB, tmp / CAT_SUB)
            # imita una exportación de SISPRO: otras columnas, cp1252, separador ;
            (tmp / CAT_OFICIAL).write_text(
                "Tabla;Código;Nombre;Descripción;Habilitado\n"
                "CIE10;A000;Cólera;Cólera;SI\nCIE10;J00X;Rinofaringitis;;SI\nCIE10;Z999;Vieja;;NO\n",
                encoding="cp1252")
            cat = cargar_catalogo(tmp, CAT_OFICIAL, CAT_SUB)
            self.assertIn("oficial", cat.origen)
            self.assertEqual(cat.codigos, {"A000", "J00X"})
            self.assertIn("Z999", cat.no_habilitados)


class TestEsquemaYaml(unittest.TestCase):
    def _mapeo(self, tmp: Path, texto: str):
        (tmp / "m.yaml").write_text(textwrap.dedent(texto), encoding="utf-8")
        return cargar_mapeo(tmp / "m.yaml", tmp)

    def test_mapeos_de_las_fuentes_1_a_3_son_validos(self):
        # Después del experimento C5 también existe el YAML de la fuente 4: todos deben ser válidos
        cfgs = configs()
        self.assertTrue({g.FUENTE1, g.FUENTE2, g.FUENTE3} <= set(cfgs))
        self.assertEqual(len(cfgs), len(descubrir_mapeos(RAIZ / "mapeos")))

    def test_plantilla_no_se_toma_como_fuente(self):
        nombres = [m.name for m in descubrir_mapeos(RAIZ / "mapeos")]
        self.assertNotIn("_plantilla.yaml", nombres)

    def test_errores_de_configuracion_con_mensajes_claros(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "f.csv").write_text("a\n1\n", encoding="utf-8")
            with self.assertRaises(ErrorConfiguracion) as e:
                self._mapeo(tmp, """
                    version_esquema: 1
                    fuente: {id: x, tipo: csv, ruta: f.csv}
                    columnas: {id_atencion: a, fecha_atencoin: b}
                    formatos_fecha: {fecha_atencion: "dd/mm/aaaa"}
                    equivalencias: {sexo: {NO: M, H: Z}}
                    """)
            msg = str(e.exception)
            self.assertIn("¿Quisiste decir 'fecha_atencion'?", msg)
            self.assertIn("Falta mapear el campo obligatorio 'sexo'", msg)
            self.assertIn("sin códigos %", msg)
            self.assertIn("entre comillas", msg)
            self.assertIn("'Z' no es un valor estándar", msg)

    def test_columna_inexistente_lista_las_disponibles(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "f.csv").write_text("id,td,nd,sx,fn,fa,dx\n", encoding="utf-8")
            cfg = self._mapeo(tmp, """
                version_esquema: 1
                fuente: {id: x, tipo: csv, ruta: f.csv}
                columnas: {id_atencion: id, tipo_documento: td, numero_documento: nd, sexo: sexo,
                           fecha_nacimiento: fn, fecha_atencion: fa, codigo_cie10: dx}
                formatos_fecha: {fecha_nacimiento: "%d/%m/%Y", fecha_atencion: "%d/%m/%Y"}
                """)
            with self.assertRaises(ErrorConfiguracion) as e:
                adaptadores.leer_fuente(cfg)
            self.assertIn("Columnas disponibles", str(e.exception))

    def test_variaciones_comunes_de_csv(self):
        """Separador ;, latin-1, encabezado en la fila 3, pie de totales, nombre en una
        columna, hora aparte, CIE-10 con punto y un valor fijo."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "f.csv").write_bytes(textwrap.dedent("""\
                REPORTE DE CONSULTAS;;;;;;
                Generado por SistemaX;;;;;;
                Código;Documento;Género;Nacimiento;Fecha;Hora;Diagnóstico;Paciente;Sede
                C-1;1045;H;25.03.1990;14.05.2026;09:30;J45.9;JOSÉ PÉREZ;Norte
                C-2;1046;M;01.12.1985;14.05.2026;10:15;I10;MARÍA ÑÚÑEZ;Sur
                C-3;1047;M;01.12.1985;15.05.2026;N/A;R51;ANA DÍAZ;Sur
                Total registros: 3;;;;;;
                """).encode("latin-1"))
            cfg = self._mapeo(tmp, """
                version_esquema: 1
                fuente: {id: variada, tipo: csv, ruta: f.csv}
                lectura: {separador: ";", codificacion: latin-1, fila_encabezado: 3, filas_pie: 1}
                columnas:
                  id_atencion: Código
                  numero_documento: Documento
                  sexo: Género
                  fecha_nacimiento: Nacimiento
                  fecha_atencion: Fecha
                  hora_atencion: Hora
                  codigo_cie10: Diagnóstico
                  nombre_completo: Paciente
                formatos_fecha: {fecha_nacimiento: "%d.%m.%Y", fecha_atencion: "%d.%m.%Y", hora_atencion: "%H:%M"}
                equivalencias: {sexo: {H: M, M: F}}
                valores_fijos: {tipo_documento: CC}
                opciones: {valores_vacios: ["", "N/A"], cie10_quitar_punto: true, cie10_completar_x: true}
                """)
            lectura, ats = extraer_atenciones(cfg, catalogo())
            self.assertEqual(len(ats), 3)
            self.assertEqual(lectura.columnas_ignoradas, ["Sede"])
            a, b, c = ats
            self.assertTrue(a.valida, a.hallazgos)
            self.assertEqual((a.codigo_cie10, a.sexo, a.tipo_documento), ("J459", "M", "CC"))
            self.assertEqual(a.fecha_atencion, datetime(2026, 5, 14, 9, 30))
            self.assertEqual(a.nombre_completo, "JOSÉ PÉREZ")
            self.assertEqual((b.codigo_cie10, b.sexo), ("I10X", "F"))
            self.assertEqual(c.fecha_atencion, date(2026, 5, 15))   # hora vacía: queda la fecha

    def test_excel_con_fechas_reales_y_numeros(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            wb = Workbook()
            ws = wb.active
            ws.title = "Datos"
            ws.append(["ID", "TD", "Doc", "Sexo", "Nac", "Atencion", "Dx"])
            ws.append([101, "CC", 1045678901, "F", datetime(1990, 3, 25), datetime(2026, 5, 14, 9, 30), "J00X"])
            wb.save(tmp / "f.xlsx")
            cfg = self._mapeo(tmp, """
                version_esquema: 1
                fuente: {id: excel_real, tipo: excel, ruta: f.xlsx}
                lectura: {hoja: Datos, fila_encabezado: 1}
                columnas: {id_atencion: ID, tipo_documento: TD, numero_documento: Doc, sexo: Sexo,
                           fecha_nacimiento: Nac, fecha_atencion: Atencion, codigo_cie10: Dx}
                formatos_fecha: {fecha_nacimiento: "%d/%m/%Y", fecha_atencion: "%d/%m/%Y"}
                """)
            _, (a,) = extraer_atenciones(cfg, catalogo())
            self.assertTrue(a.valida, a.hallazgos)
            self.assertEqual((a.id_atencion, a.numero_documento), ("101", "1045678901"))
            self.assertEqual(a.fecha_nacimiento, date(1990, 3, 25))


if __name__ == "__main__":
    unittest.main()
