"""La prueba exploratoria corre, se reporta aparte y no toca C1–C5."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from generador_sintetico import generador as g
from saludia.conector import ejecutar
from saludia.exploratorio import ETIQUETA, correr_exploratorio
from saludia.metricas import calcular_metricas

RAIZ = Path(__file__).resolve().parent.parent
EXCLUIR = shutil.ignore_patterns(".venv", "venv", "__pycache__", "salidas", ".git", "*.zip")


class TestExploratorio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        g.generar()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.raiz = Path(cls.tmp.name) / "p"
        shutil.copytree(RAIZ, cls.raiz, ignore=EXCLUIR)
        (cls.raiz / "salidas").mkdir()
        cls.res = correr_exploratorio(cls.raiz)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_doce_casos_en_dos_variantes_con_etiqueta(self):
        self.assertEqual(self.res["etiqueta"], ETIQUETA)
        self.assertIn("fuera de los criterios", ETIQUETA)
        self.assertEqual([v["variante"] for v in self.res["variantes"]], ["A", "B"])
        for v in self.res["variantes"]:
            self.assertEqual(len(v["casos"]), 12)
            self.assertEqual(sum(v["resumen"].values()), 12)
        md = (self.raiz / "salidas" / "hallazgos_exploratorios.md").read_text(encoding="utf-8")
        self.assertTrue(md.startswith(f"# {ETIQUETA}"))

    def test_no_altera_los_criterios(self):
        corrida = ejecutar(self.raiz)
        m = calcular_metricas(corrida, self.raiz)
        self.assertEqual([f.id for f in corrida.fuentes], ["fuente1_sqlite", "fuente2_csv", "fuente3_excel"])
        self.assertEqual(m["criterios"]["C1"]["detalle"]["en_fuentes_conteo_independiente"], 300)
        self.assertEqual(m["criterios"]["C3"]["detalle"]["sembrados"], 30)
        self.assertNotIn("exploratorio", json.dumps(m, ensure_ascii=False))

    def test_sus_mapeos_no_estan_en_la_carpeta_de_fuentes(self):
        # así no se confunden con la fuente 4 en el cronómetro de C5
        self.assertFalse(list((RAIZ / "mapeos").glob("*exploratorio*")))


if __name__ == "__main__":
    unittest.main()
