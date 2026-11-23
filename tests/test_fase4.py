"""Pruebas del motor FHIR, la validación estructural y las salidas."""
import builtins
import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fhir.resources

from generador_sintetico import generador as g
from saludia.conector import ejecutar
from saludia.modelo import AtencionComun, RegistroCrudo
from saludia.motor_fhir import construir_bundle, icd10_oms
from saludia.salidas import escribir_ejemplo_rda, escribir_reporte_errores
from saludia.validacion_fhir import validar_bundle

RAIZ = Path(__file__).resolve().parent.parent


class BaseCorrida(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        g.generar()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.salidas = Path(cls.tmp.name) / "salidas"
        cls.corrida = ejecutar(RAIZ, dir_salidas=cls.salidas)
        cls.validos = [r for r in cls.corrida.registros() if r.bundle is not None]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class TestVersionFhir(unittest.TestCase):
    def test_libreria_es_r4(self):
        self.assertEqual(fhir.resources.__fhir_version__, "4.0.1")


class TestEstructuraBundle(BaseCorrida):
    """El RDA es un Bundle document con Composition, Patient, Encounter y Condition."""

    def test_estructura_pedida(self):
        self.assertEqual(len(self.validos), 270)
        for rr in self.validos:
            b = rr.bundle
            self.assertEqual(b["type"], "document")
            tipos = [e["resource"]["resourceType"] for e in b["entry"]]
            self.assertEqual(tipos, ["Composition", "Patient", "Encounter", "Condition"])
            comp, pac, enc, cond = (e["resource"] for e in b["entry"])
            url = {e["resource"]["resourceType"]: e["fullUrl"] for e in b["entry"]}
            self.assertTrue(all(u.startswith("urn:uuid:") for u in url.values()))
            self.assertEqual(comp["status"], "final")
            self.assertEqual(comp["type"]["coding"][0]["code"], "34133-9")
            self.assertTrue(comp["author"] and "display" in comp["author"][0])
            self.assertEqual(comp["section"][0]["entry"][0]["reference"], url["Condition"])
            self.assertEqual(enc["status"], "finished")
            self.assertEqual(enc["class"]["code"], "AMB")
            self.assertEqual(cond["subject"]["reference"], url["Patient"])
            self.assertEqual(cond["code"]["coding"][0]["system"], "http://hl7.org/fhir/sid/icd-10")
            self.assertIn(pac["gender"], ("male", "female"))

    def test_todos_los_bundles_pasan_la_validacion(self):
        for rr in self.validos:
            self.assertTrue(rr.validacion.valido, rr.validacion.errores)

    def test_uuid_deterministas(self):
        rr = self.validos[0]
        otra = construir_bundle(rr.atencion, mock.MagicMock(nombres={}), mock.MagicMock(
            nombre_ips="x", marca_tiempo=self.corrida.inicio, zona=self.corrida.inicio.tzinfo))
        self.assertEqual([e["fullUrl"] for e in otra["entry"]], [e["fullUrl"] for e in rr.bundle["entry"]])

    def test_cie10_formato_oms(self):
        self.assertEqual(icd10_oms("J00X"), "J00")
        self.assertEqual(icd10_oms("J459"), "J45.9")
        self.assertEqual(icd10_oms("I10X"), "I10")


class TestValidacionDetectaBundlesMalos(BaseCorrida):
    """La validación no aprueba cualquier cosa: cada regla rechaza su caso."""

    def _mutar(self, funcion):
        b = copy.deepcopy(self.validos[0].bundle)
        funcion(b)
        return validar_bundle(b)

    def _recurso(self, b, tipo):
        return next(e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == tipo)

    def test_casos_rechazados(self):
        casos = {
            "type inválido": lambda b: b.update(type="documento"),
            "sin identifier (bdl-9)": lambda b: b.pop("identifier"),
            "sin timestamp (bdl-10)": lambda b: b.pop("timestamp"),
            "Composition no es la primera (bdl-11)": lambda b: b["entry"].reverse(),
            "fullUrl repetido (bdl-7)": lambda b: b["entry"][1].update(fullUrl=b["entry"][0]["fullUrl"]),
            "referencia rota": lambda b: self._recurso(b, "Condition")["subject"].update(
                reference="urn:uuid:00000000-0000-0000-0000-000000000000"),
            "Encounter sin class (R4)": lambda b: self._recurso(b, "Encounter").pop("class"),
            "Composition sin author (R4)": lambda b: self._recurso(b, "Composition").pop("author"),
            "gender inventado": lambda b: self._recurso(b, "Patient").update(gender="masculino"),
            "status inventado": lambda b: self._recurso(b, "Encounter").update(status="terminado"),
            "fecha con hora sin zona": lambda b: self._recurso(b, "Encounter")["period"].update(
                start="2026-01-06T11:25:00"),
            "fecha imposible (R4)": lambda b: self._recurso(b, "Patient").update(birthDate="1985-02-29"),
            "falta Condition": lambda b: b["entry"].pop(3),
            "Condition sin CIE-10": lambda b: self._recurso(b, "Condition")["code"].update(
                coding=[{"system": "http://snomed.info/sct", "code": "1"}]),
            "sección sin Condition": lambda b: self._recurso(b, "Composition")["section"][0].update(entry=[]),
        }
        for nombre, f in casos.items():
            with self.subTest(nombre):
                self.assertFalse(self._mutar(f).valido, f"no rechazó: {nombre}")


class TestReglaModeloComunAntesDeFhir(unittest.TestCase):
    """Regla 2: las fuentes pasan primero al modelo común y después a FHIR."""

    def test_motor_rechaza_filas_crudas(self):
        for entrada in ({"id_aten": 1}, RegistroCrudo("f", 1, {"a": 1})):
            with self.assertRaises(TypeError):
                construir_bundle(entrada, None, None)

    def test_motor_no_importa_adaptadores_ni_mapeo(self):
        codigo = (RAIZ / "saludia" / "motor_fhir.py").read_text(encoding="utf-8")
        for prohibido in ("adaptadores", "mapeo", "pandas", "sqlite3", "openpyxl"):
            self.assertNotIn(f"import {prohibido}", codigo)
            self.assertNotIn(f"from .{prohibido}", codigo)

    def test_registro_con_error_no_genera_rda(self):
        at = AtencionComun("f", 1)
        at.agregar("sexo", "campo_obligatorio_vacio", "", "vacío")
        with self.assertRaises(ValueError):
            construir_bundle(at, None, None)


class TestSalidasYErrores(BaseCorrida):
    def test_un_json_por_atencion_valida_y_ninguno_por_las_invalidas(self):
        archivos = list((self.salidas / "rda").rglob("*.json"))
        self.assertEqual(len(archivos), 270)
        for rr in self.corrida.registros():
            if not rr.atencion.valida:
                self.assertIsNone(rr.bundle)
                self.assertIsNone(rr.archivo_rda)
        json.loads(archivos[0].read_text(encoding="utf-8"))

    def test_reporte_de_errores_y_ejemplo(self):
        ruta_csv, ruta_json = escribir_reporte_errores(self.corrida, self.salidas)
        with open(ruta_csv, encoding="utf-8-sig") as f:
            filas = list(csv.DictReader(f))
        self.assertEqual(list(filas[0]), ["id_atencion", "fuente", "fila", "campo", "tipo_error",
                                          "valor_encontrado", "mensaje"])
        self.assertEqual(len({(r["fuente"], r["fila"]) for r in filas}), 30)
        ej = escribir_ejemplo_rda(self.corrida, self.salidas)
        self.assertTrue(validar_bundle(json.loads(ej.read_text(encoding="utf-8"))).valido)

    def test_fuentes_intactas(self):
        for f in self.corrida.fuentes:
            self.assertTrue(f.intacta, f.id)

    def test_tiempo_medido_por_registro(self):
        tiempos = [r.segundos for r in self.corrida.registros()]
        self.assertEqual(len(tiempos), 300)
        self.assertTrue(all(t > 0 for t in tiempos))


class TestNuncaSeLeeLaListaDeErroresSembrados(unittest.TestCase):
    """El conector (lectura, validación, FHIR) nunca abre errores_sembrados.csv."""

    def test_en_ejecucion(self):
        abrir_real = builtins.open

        def guardia(archivo, *a, **k):
            if "errores_sembrados" in str(archivo):
                raise AssertionError(f"El conector intentó leer {archivo}")
            return abrir_real(archivo, *a, **k)

        with tempfile.TemporaryDirectory() as tmp, mock.patch("builtins.open", guardia), \
                mock.patch("io.open", guardia):
            corrida = ejecutar(RAIZ, dir_salidas=Path(tmp))
        self.assertEqual(sum(1 for _ in corrida.registros()), 300)

    def test_en_el_codigo(self):
        permitidos = {"metricas.py"}       # solo el módulo de métricas puede usarla (C3)
        for py in (RAIZ / "saludia").glob("*.py"):
            if py.name in permitidos:
                continue
            self.assertNotIn("errores_sembrados", py.read_text(encoding="utf-8"), py.name)


if __name__ == "__main__":
    unittest.main()
