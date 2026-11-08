"""Pruebas de la interfaz con el agente real y decisiones simuladas, sin Ollama."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from src.agent import AgenteViajes, ErrorOllama
from test_agent import ClienteSimulado, coste, propuesta

if importlib.util.find_spec("streamlit"):
    from streamlit.testing.v1 import AppTest


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Instala la dependencia opcional interfaz.")
class TestInterfaz(unittest.TestCase):
    def abrir(self, respuestas=()):
        cliente = ClienteSimulado(respuestas)
        with patch("src.agent.AgenteViajes", side_effect=lambda **kwargs: AgenteViajes(cliente, **kwargs)):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
        self.assertFalse(app.exception)
        return app, cliente

    def test_inicio_sin_consultar_ollama(self):
        app, cliente = self.abrir()
        self.assertIn("ViajeSIBI", app.title[0].value)
        self.assertEqual(cliente.peticiones, [])
        self.assertEqual(len(app.chat_input), 1)

    def test_historial_persiste_entre_mensajes(self):
        app, cliente = self.abrir([
            {"role": "assistant", "content": "¿Cuántos días?"},
            {"role": "assistant", "content": "¿Cuántos viajeros?"},
        ])
        app.chat_input[0].set_value("Salimos desde Madrid.").run()
        app.chat_input[0].set_value("Cuatro días.").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.chat_message), 4)
        self.assertEqual(cliente.peticiones[1][1]["content"], "Salimos desde Madrid.")

    def test_tabla_verificada_y_herramientas_desplegables(self):
        app, _ = self.abrir([coste("oporto"), propuesta(["oporto"], "recomendacion", 800)])
        app.chat_input[0].set_value("Somos 2 personas, 4 días desde Madrid, cultura y 800 EUR en total. Recomienda un destino.").run()
        self.assertFalse(app.exception)
        contenido = "\n".join(elemento.value for elemento in app.markdown)
        self.assertIn("770 EUR", contenido)
        self.assertIn("30 EUR", contenido)
        self.assertEqual(app.expander[0].label, "Herramientas y validaciones")
        self.assertIn("estimar_coste", app.code[0].value)

    def test_error_de_ollama_se_muestra_y_permite_reintentar(self):
        app, _ = self.abrir([ErrorOllama("Abre Ollama"), {"role": "assistant", "content": "¿Cuántos días?"}])
        app.chat_input[0].set_value("Salimos desde Madrid").run()
        self.assertEqual(app.error[0].value, "Abre Ollama")
        app.chat_input[0].set_value("Salimos desde Madrid").run()
        self.assertFalse(app.exception)
        self.assertIn("¿Cuántos días?", app.markdown[-1].value)

    def test_nueva_conversacion_borra_agente_y_mensajes(self):
        app, _ = self.abrir()
        app.chat_input[0].set_value("Tenemos 1400").run()
        anterior = app.session_state["agente"]
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.chat_message), 0)
        self.assertIsNot(app.session_state["agente"], anterior)
        self.assertEqual(len(app.session_state["agente"].historial), 1)
