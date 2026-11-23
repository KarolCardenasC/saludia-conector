"""Pruebas de las métricas C1–C5 y del cronómetro de C5."""
import copy
import importlib.util
import json
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from generador_sintetico import generador as g
from saludia.conector import ejecutar
from saludia.metricas import calcular_metricas, cargar_metas, cumple

RAIZ = Path(__file__).resolve().parent.parent
EXCLUIR = shutil.ignore_patterns(".venv", "venv", "__pycache__", "salidas", ".git", "*.zip")


def copiar_proyecto(destino: Path) -> Path:
    raiz = destino / "proyecto"
    shutil.copytree(RAIZ, raiz, ignore=EXCLUIR)
    (raiz / "salidas").mkdir()
    return raiz


def cargar_cronometro():
    spec = importlib.util.spec_from_file_location("c5_cronometro", RAIZ / "scripts" / "c5_cronometro.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMetricas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        g.generar()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.raiz = copiar_proyecto(Path(cls.tmp.name))
        cls.corrida = ejecutar(cls.raiz)
        cls.m = calcular_metricas(cls.corrida, cls.raiz)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_metas_salen_del_archivo_y_no_cambiaron(self):
        metas = cargar_metas(RAIZ)
        self.assertTrue(metas["_sin_cambios"], "metas.yaml no coincide con config/metas.sha256")
        for k in ("C1", "C2", "C3", "C4"):
            self.assertEqual(self.m["criterios"][k]["meta"], metas["criterios"][k]["meta"])
        self.assertEqual((metas["criterios"]["C1"]["meta"], metas["criterios"]["C2"]["meta"],
                          metas["criterios"]["C3"]["meta"], metas["criterios"]["C4"]["meta"]),
                         (95.0, 90.0, 100.0, 1.0))

    def test_c1_usa_conteo_independiente(self):
        d = self.m["criterios"]["C1"]["detalle"]
        self.assertEqual(d["en_fuentes_conteo_independiente"], 300)
        self.assertEqual(d["extraidos"], 300)          # los 30 con error también cuentan
        codigo = (RAIZ / "saludia" / "metricas.py").read_text(encoding="utf-8")
        cuerpo = codigo.split("def contar_registros_independiente")[1].split("\ndef ")[0]
        self.assertNotIn("pd.", cuerpo)
        self.assertNotIn("leer_fuente", cuerpo)

    def test_c2_sobre_270(self):
        d = self.m["criterios"]["C2"]["detalle"]
        self.assertEqual(d["registros_sin_error_sembrado"], 270)

    def test_c3_y_falsos_positivos(self):
        d = self.m["criterios"]["C3"]["detalle"]
        self.assertEqual((d["sembrados"], d["detectados"], d["falsos_positivos"]), (30, 30, 0))

    def test_c3_baja_si_un_error_no_se_detecta(self):
        corrida = copy.deepcopy(self.corrida)
        sembrado = next(r for r in corrida.registros() if not r.atencion.valida)
        sembrado.atencion.hallazgos.clear()            # simula un error que se escapó
        m = calcular_metricas(corrida, self.raiz)
        self.assertAlmostEqual(m["criterios"]["C3"]["resultado"], 96.67)
        self.assertFalse(m["criterios"]["C3"]["cumplio"])
        self.assertEqual(len(m["criterios"]["C3"]["detalle"]["no_detectados"]), 1)

    def test_falso_positivo_se_reporta_y_baja_c2(self):
        corrida = copy.deepcopy(self.corrida)
        normal = next(r for r in corrida.registros() if r.atencion.valida)
        normal.atencion.agregar("sexo", "valor_no_reconocido", "X", "simulado")
        normal.validacion = None
        normal.bundle = None
        m = calcular_metricas(corrida, self.raiz)
        self.assertEqual(m["criterios"]["C3"]["detalle"]["falsos_positivos"], 1)
        self.assertLess(m["criterios"]["C2"]["resultado"], 100)

    def test_c4_estadisticas(self):
        d = self.m["criterios"]["C4"]["detalle"]
        self.assertEqual(d["atenciones"], 300)
        for k in ("promedio_s", "mediana_s", "maximo_s", "total_corrida_s"):
            self.assertIsNotNone(d[k])

    def test_c5_pendiente_sin_cronometro_y_h2_pendiente(self):
        self.assertEqual(self.m["criterios"]["C5"]["resultado"], "pendiente")
        self.assertIsNone(self.m["criterios"]["C5"]["cumplio"])
        self.assertEqual(self.m["hipotesis_h2"]["estado"], "pendiente")

    def test_c5_se_lee_de_c5_json(self):
        (self.raiz / "salidas" / "c5.json").write_text(json.dumps({"veredicto": "si", "segundos": 600}))
        try:
            m = calcular_metricas(self.corrida, self.raiz)
            self.assertTrue(m["criterios"]["C5"]["cumplio"])
            self.assertEqual(m["hipotesis_h2"]["estado"], "confirmada en entorno simulado")
        finally:
            (self.raiz / "salidas" / "c5.json").unlink()

    def test_operadores(self):
        self.assertTrue(cumple(">=", 95.0, 95.0))
        self.assertFalse(cumple(">=", 94.99, 95.0))
        self.assertTrue(cumple("<=", 1.0, 1.0))
        self.assertFalse(cumple("<=", 1.01, 1.0))
        self.assertIsNone(cumple(">=", None, 95.0))


class TestCronometroC5(unittest.TestCase):
    """Flujo completo con una fuente de PRUEBA inventada para el test (no es la fuente 4)."""

    CSV = "codigo|doc|tdoc|sx|nac|fecha|dx\nP-1|111|C|H|1990/01/02|2026/05/14|J00X\nP-2|222|T|M|2012/03/04|2026/05/15|R51X\n"
    YAML = textwrap.dedent("""
        version_esquema: 1
        fuente: {id: prueba_c5, tipo: csv, ruta: datos/fuentes/prueba_c5.csv}
        lectura: {separador: "|"}
        columnas: {id_atencion: codigo, numero_documento: doc, tipo_documento: tdoc, sexo: sx,
                   fecha_nacimiento: nac, fecha_atencion: fecha, codigo_cie10: dx}
        formatos_fecha: {fecha_nacimiento: "%Y/%m/%d", fecha_atencion: "%Y/%m/%d"}
        equivalencias: {sexo: {H: M, M: F}, tipo_documento: {C: CC, T: TI}}
        """)
    ESPERADO = ("id_atencion,tipo_documento,numero_documento,sexo,fecha_nacimiento,fecha_atencion,"
                "codigo_cie10,esperado_valido\nP-1,CC,111,M,1990-01-02,2026-05-14,J00X,si\n"
                "P-2,TI,222,F,2012-03-04,2026-05-15,R51X,si\n")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = copiar_proyecto(Path(self.tmp.name))
        self.c5 = cargar_cronometro()
        (self.raiz / "datos/fuentes/prueba_c5.csv").write_text(self.CSV, encoding="utf-8")
        (self.raiz / "datos/fuentes/esperado_prueba.csv").write_text(self.ESPERADO, encoding="utf-8")
        self.c5.congelar(self.raiz)
        self.c5.inicio(self.raiz)

    def tearDown(self):
        self.tmp.cleanup()

    def _yaml(self, texto):
        (self.raiz / "mapeos/prueba_c5.yaml").write_text(texto, encoding="utf-8")

    # Se indica el YAML explícitamente: después del experimento C5 real, mapeos/ también
    # contiene el YAML de la fuente 4.
    MAPEO = "mapeos/prueba_c5.yaml"

    def _fin(self):
        return self.c5.fin(self.raiz, mapeo=self.MAPEO, esperado="datos/fuentes/esperado_prueba.csv")

    def test_flujo_exitoso_con_intento_fallido(self):
        self._yaml(self.YAML.replace("codigo_cie10: dx", "codigo_cie10: diagnostico"))
        r1 = self.c5.intento(self.raiz, mapeo=self.MAPEO)
        self.assertEqual(r1["resultado"], "no_conectada")
        self._yaml(self.YAML)
        r2 = self.c5.intento(self.raiz, mapeo=self.MAPEO)
        self.assertEqual((r2["resultado"], r2["bundles_validos"]), ("conectada", 2))
        res = self._fin()
        self.assertEqual(res["veredicto"], "si", res["motivos"])
        self.assertEqual(res["intentos"], 2)
        self.assertTrue(all(res["verificaciones"].values()))
        self.assertIn("prueba_c5", res["mapeo"]["contenido"])
        guardado = json.loads((self.raiz / "salidas/c5.json").read_text(encoding="utf-8"))
        self.assertEqual(guardado["veredicto"], "si")

    def test_modificar_codigo_da_no(self):
        self._yaml(self.YAML)
        py = self.raiz / "saludia" / "normalizador.py"
        py.write_text(py.read_text(encoding="utf-8") + "\n# cambio\n", encoding="utf-8")
        res = self._fin()
        self.assertEqual(res["veredicto"], "no")
        self.assertIn("saludia/normalizador.py", res["codigo_congelado"]["cambios"]["modificados"])

    def test_modificar_yaml_de_fuentes_1_a_3_da_no(self):
        self._yaml(self.YAML)
        y = self.raiz / "mapeos" / "fuente2_csv.yaml"
        y.write_text(y.read_text(encoding="utf-8") + "\n# cambio\n", encoding="utf-8")
        self.assertEqual(self._fin()["veredicto"], "no")

    def test_diferencia_con_el_esperado_da_parcial(self):
        self._yaml(self.YAML.replace("{H: M, M: F}", "{H: F, M: M}"))   # equivalencia invertida
        res = self._fin()
        self.assertEqual(res["veredicto"], "parcial")
        self.assertEqual(res["comparacion_esperado"]["diferencias"], 2)

    def test_sin_esperado_da_parcial(self):
        self._yaml(self.YAML)
        res = self.c5.fin(self.raiz, mapeo=self.MAPEO, esperado="datos/fuentes/no_existe.csv")
        self.assertEqual(res["veredicto"], "parcial")


if __name__ == "__main__":
    unittest.main()
