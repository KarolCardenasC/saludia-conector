"""Pruebas de la terminal, el dashboard HTML y main.py de punta a punta."""
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from saludia import LEYENDA
from saludia.consola import Consola, largo_visible

RAIZ = Path(__file__).resolve().parent.parent
EXCLUIR = shutil.ignore_patterns(".venv", "venv", "__pycache__", "salidas", ".git", "*.zip")
ANSI = re.compile(r"\x1b\[")


class TestConsola(unittest.TestCase):
    def test_sin_color_no_emite_ansi(self):
        buf = io.StringIO()
        con = Consola(color=False, flujo=buf)
        con.banner("Título", "Sub", LEYENDA)
        con.tabla(["a", "b"], [[con.ok(), con.mal()], [con.pendiente(), "x"]])
        self.assertIsNone(ANSI.search(buf.getvalue()))
        self.assertIn("✓ sí", buf.getvalue())

    def test_con_color_emite_ansi_y_la_tabla_queda_alineada(self):
        buf = io.StringIO()
        con = Consola(color=True, flujo=buf)
        con.tabla(["Criterio", "¿Cumplió?"], [["C1", con.ok()], ["C5", con.pendiente()]])
        lineas = buf.getvalue().splitlines()
        self.assertIsNotNone(ANSI.search(buf.getvalue()))
        self.assertEqual(len({largo_visible(l) for l in lineas}), 1)

    def test_salida_redirigida_sin_color_por_defecto(self):
        self.assertFalse(Consola(flujo=io.StringIO()).color)

    def test_salida_redirigida_en_utf8_aunque_el_sistema_use_otra_codificacion(self):
        """Simula Windows: la tubería usaría cp1252; la salida debe llegar en UTF-8."""
        import os
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        r = subprocess.run([sys.executable, "-c",
                            "from saludia.consola import preparar_salida; preparar_salida(); print('✓ · ─ ñ')"],
                           cwd=RAIZ, capture_output=True, env=env, timeout=60)
        self.assertEqual(r.stdout.decode("utf-8").strip(), "✓ · ─ ñ")


class TestPuntaAPunta(unittest.TestCase):
    """main.py corre completo en una copia limpia del proyecto: generar-datos → ejecutar."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.raiz = Path(cls.tmp.name) / "proyecto"
        shutil.copytree(RAIZ, cls.raiz, ignore=EXCLUIR)

        def correr(*args):
            # errors="replace": si la salida no viniera en UTF-8, la prueba falla con un
            # mensaje claro en vez de perder la salida (caso visto en Windows con cp1252)
            return subprocess.run([sys.executable, "main.py", *args, "--sin-color"], cwd=cls.raiz,
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=600)

        cls.gen = correr("generar-datos")
        cls.eje = correr("ejecutar")
        cls.sal = cls.raiz / "salidas"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_comandos_terminan_bien(self):
        self.assertEqual(self.gen.returncode, 0, self.gen.stderr)
        self.assertEqual(self.eje.returncode, 0, self.eje.stderr)
        self.assertIn("Resultado: ✓ OK", self.gen.stdout)
        self.assertIsNone(ANSI.search(self.eje.stdout))
        for texto in ("FHIR 4.0.1", LEYENDA, "Criterios de éxito", "C5", "dashboard.html"):
            self.assertIn(texto, self.eje.stdout)

    def test_salidas_existen(self):
        for nombre in ("ejemplo_rda.json", "reporte_errores.csv", "reporte_errores.json",
                       "metricas.json", "corrida.json", "dashboard.html"):
            self.assertTrue((self.sal / nombre).exists(), nombre)
        self.assertEqual(len(list((self.sal / "rda").rglob("*.json"))), 270)

    def test_dashboard_autocontenido(self):
        html = (self.sal / "dashboard.html").read_text(encoding="utf-8")
        self.assertNotRegex(html, r"<script[^>]+src=")
        self.assertNotRegex(html, r"<link[^>]+href=")
        self.assertNotIn("@import", html)
        self.assertNotRegex(html, r"url\(\s*['\"]?https?:")
        self.assertNotRegex(html, r"<img[^>]+src=\"https?:")

    def test_dashboard_honesto_y_con_datos_reales(self):
        html = (self.sal / "dashboard.html").read_text(encoding="utf-8")
        met = json.loads((self.sal / "metricas.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(html.count(LEYENDA), 2)                 # encabezado y pie
        self.assertIn("no está certificado ni aprobado", html)
        self.assertIn(met["version_fhir"], html)
        self.assertIn("Pendiente", html)                              # C5 sin ejecutar
        self.assertIn("no se simula ni se rellena", html)
        validos = met["criterios"]["C2"]["detalle"]["bundles_validos_total"]
        self.assertIn(f'data-valor="{validos}"', html)
        # Ninguna afirmación de certificación o conformidad (las aclaraciones negativas sí se permiten)
        texto = " ".join(re.sub(r"<[^>]+>", " ", html.split("<body>")[1]).split())
        self.assertIn("no está certificado ni aprobado por", texto)
        self.assertIn("no implica conformidad con", texto)
        for negacion in ("no está certificado ni aprobado por", "no implica conformidad con",
                         "no es conformidad con"):
            texto = texto.replace(negacion, "")
        for afirmacion in (r"certificad[oa]", r"aprobad[oa] por", r"cumple (con )?la Resoluci",
                           r"conformidad con la gu", r"conforme (con|a) la gu"):
            self.assertNotRegex(texto, afirmacion)
        for seccion in ("Recorrido del dato", "Criterios de éxito", "Atenciones por fuente",
                        "Errores por tipo", "Tiempo por atención", "Tres fuentes distintas",
                        "Reporte de errores", "RDA de ejemplo", "C5 · Fuente nueva"):
            self.assertIn(seccion, html)


if __name__ == "__main__":
    unittest.main()
