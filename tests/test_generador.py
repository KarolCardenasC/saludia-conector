"""Pruebas del generador de datos sintéticos."""
import csv
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from generador_sintetico import generador as g
from generador_sintetico.verificar import verificar

RAIZ = g.RAIZ


def _leer_verdad(raiz=RAIZ):
    with open(raiz / "datos" / "errores_sembrados.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class TestGenerador(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.man = g.generar()

    def test_300_atenciones_100_por_fuente(self):
        self.assertEqual(self.man["total_atenciones"], 300)
        for r in self.man["fuentes"].values():
            self.assertEqual(r["registros"], 100)

    def test_30_errores_10_por_fuente_y_10_por_tipo(self):
        verdad = _leer_verdad()
        self.assertEqual(len(verdad), 30)
        self.assertEqual(Counter(v["fuente"] for v in verdad),
                         {g.FUENTE1: 10, g.FUENTE2: 10, g.FUENTE3: 10})
        self.assertEqual(Counter(v["tipo_error"] for v in verdad),
                         {"cie10_inexistente": 10, "fecha_invalida": 10,
                          "campo_obligatorio_vacio": 10})
        # un solo error por registro
        self.assertEqual(len({(v["fuente"], v["fila"]) for v in verdad}), 30)

    def test_datos_normales_validos_y_sembrados_fallan_donde_deben(self):
        v = verificar()
        self.assertEqual(v["problemas"], [])
        self.assertTrue(v["ok"])

    def test_codigos_cie10_sembrados_no_existen_en_catalogo(self):
        catalogo = set(g.cargar_codigos_catalogo(
            RAIZ / "datos" / "referencia" / "cie10_subconjunto.csv"))
        for lista in g.CIE10_INEXISTENTES.values():
            for c in lista:
                self.assertNotIn(c, catalogo)

    def test_catalogo_incluye_codigos_pedidos_y_formato_sispro(self):
        catalogo = g.cargar_codigos_catalogo(
            RAIZ / "datos" / "referencia" / "cie10_subconjunto.csv")
        self.assertTrue(200 <= len(catalogo) <= 300)
        self.assertEqual(len(catalogo), len(set(catalogo)))
        for c in g.FRECUENTES:
            self.assertIn(c, catalogo)
        for c in catalogo:
            self.assertEqual(len(c), 4, c)
            self.assertNotIn(".", c)

    def test_formatos_distintos_entre_fuentes(self):
        for mapa in (g.COLUMNAS, g.FORMATO_FECHA, g.SEXO, g.TIPO_DOC):
            vistos = [tuple(sorted(m.items())) for m in mapa.values()]
            self.assertEqual(len(set(vistos)), 3, "dos fuentes comparten formato")

    def test_reproducible_con_la_misma_semilla(self):
        antes = json.loads((RAIZ / "datos" / "manifiesto_datos.json").read_text("utf-8"))
        despues = g.generar()
        self.assertEqual(antes["sha256_contenido"], despues["sha256_contenido"])
        self.assertEqual(antes["sha256_errores_sembrados"], despues["sha256_errores_sembrados"])


if __name__ == "__main__":
    unittest.main()
