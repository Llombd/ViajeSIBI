"""Pruebas de la pantalla de ofertas sin consumir búsquedas de SerpApi."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

if importlib.util.find_spec("streamlit"):
    from streamlit.testing.v1 import AppTest


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Instala la dependencia opcional interfaz.")
class TestInterfaz(unittest.TestCase):
    def abrir(self, clave=""):
        temporal = TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        entorno = patch.dict("os.environ", {"SERPAPI_API_KEY": clave,
                                          "VIAJESIBI_DB": str(Path(temporal.name) / "perfil.sqlite3")})
        entorno.start()
        self.addCleanup(entorno.stop)
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
        self.assertFalse(app.exception)
        return app

    def test_pantalla_unica_sin_destino_ni_fechas_obligatorias(self):
        app = self.abrir("clave-ficticia")
        self.assertIn("Planificar viaje", app.title[0].value)
        self.assertEqual(app.radio[0].value, "Me da igual")
        self.assertFalse(app.date_input)
        self.assertFalse(app.sidebar.radio)
        self.assertEqual([campo.label for campo in app.selectbox], ["¿Desde dónde sales?"])

    def test_modos_de_fechas_muestran_solo_sus_campos(self):
        app = self.abrir("clave-ficticia")
        app.radio[0].set_value("Tengo un mes aproximado").run()
        self.assertFalse(app.date_input)
        self.assertEqual(app.selectbox[-1].label, "Mes aproximado")
        for modo in ("Tengo un intervalo flexible", "Tengo fechas exactas"):
            app.radio[0].set_value(modo).run()
            self.assertEqual(len(app.date_input), 2)
        self.assertFalse(app.exception)

    def test_busqueda_sin_fechas_usa_destino_elegido_por_modelo(self):
        app = self.abrir()
        app.text_input[0].set_value("clave-ficticia").run()
        app.selectbox[0].set_value("VLC")
        with (
            patch("src.agent.ClienteOllama.consultar_json",
                  return_value='{"busquedas":[{"aeropuerto":"OPO","fechas":0}]}'),
            patch("src.interfaz_ofertas.consultar_serpapi", return_value={}) as consultar,
        ):
            app.button[0].click().run()
        clave, parametros = consultar.call_args_list[0].args
        self.assertEqual(clave, "clave-ficticia")
        self.assertEqual(parametros["departure_id"], "VLC")
        self.assertEqual(parametros["arrival_id"], "OPO")
        self.assertEqual(app.text_input[0].value, "clave-ficticia")
        self.assertFalse(app.exception)
