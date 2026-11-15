"""Pruebas de la pantalla de ofertas sin consumir búsquedas de SerpApi."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from test_equipo_viaje import modelo_equipo

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
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=10).run()
        self.assertFalse(app.exception)
        return app

    def test_pantalla_unica_sin_destino_ni_fechas_obligatorias(self):
        app = self.abrir("clave-ficticia")
        self.assertIn("Planificar viaje", app.title[0].value)
        self.assertEqual(app.radio[0].value, "Me da igual")
        self.assertFalse(app.date_input)
        self.assertFalse(app.sidebar.radio)
        self.assertEqual([campo.label for campo in app.selectbox], ["¿Desde dónde sales?", "Valoración mínima de huéspedes"])

    def test_modos_de_fechas_muestran_solo_sus_campos(self):
        app = self.abrir("clave-ficticia")
        app.radio[0].set_value("Tengo un mes aproximado").run()
        self.assertFalse(app.date_input)
        self.assertEqual(app.selectbox[1].label, "Mes aproximado")
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
                  side_effect=modelo_equipo),
            patch("src.interfaz_ofertas.consultar_serpapi", return_value={}) as consultar,
        ):
            app.button[0].click().run()
        clave, parametros = consultar.call_args_list[0].args
        self.assertEqual(clave, "clave-ficticia")
        self.assertEqual(parametros["departure_id"], "VLC")
        self.assertEqual(parametros["arrival_id"], "OPO")
        self.assertEqual(app.text_input[0].value, "clave-ficticia")
        self.assertFalse(app.exception)

    def test_propone_fijar_aeropuerto_despues_de_dos_rechazos(self):
        from datetime import date

        app = self.abrir("clave-ficticia")
        plan = dict(ciudad="Oporto", salida="VLL", total=600, vuelo=200, alojamiento=400,
                    nombre="Hotel de prueba", ida_fecha=date(2027, 2, 10),
                    vuelta_fecha=date(2027, 2, 13), ida=[], vuelta=[])
        for identificador in ("primera", "segunda"):
            app.session_state["resultado_con_aprendizaje"] = (
                [plan], [], None, 800, "LEN", 2, 100, identificador,
            )
            app.run()
            next(boton for boton in app.button if boton.label.startswith("Para este viaje")).click().run()
            sugerencia = [boton for boton in app.button if boton.label.startswith("Recordar que prefiero")]
            self.assertEqual(len(sugerencia), int(identificador == "segunda"))
        sugerencia[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.session_state["perfil_ofertas"]["origen_fijo"])

    def test_limite_por_persona_descarta_ofertas_incluso_con_impuestos_pendientes(self):
        from datetime import date

        app = self.abrir("clave-ficticia")
        base = dict(ciudad="Barcelona", vuelo=400, alojamiento=650,
                    ida_fecha=date(2027, 2, 10), vuelta_fecha=date(2027, 2, 13),
                    ida=[], vuelta=[], impuestos_confirmados=False)
        app.session_state["resultado_con_aprendizaje"] = (
            [dict(base, total=1050, nombre="Dentro del margen"),
             dict(base, total=1389, nombre="Fuera provisional"),
             dict(base, total=2018, nombre="Fuera confirmado", impuestos_confirmados=True)],
            [], None, 1000, "LEN", 2, 100, "prueba",
        )
        app.run()
        self.assertFalse(app.exception)
        titulos = [elemento.value for elemento in app.subheader]
        self.assertIn("Barcelona · 1050.00 €", titulos)
        self.assertNotIn("Barcelona · 1389.00 €", titulos)
        self.assertNotIn("Barcelona · 2018.00 €", titulos)

    def test_demostracion_reproduce_oferta_sin_api_ni_modelo(self):
        from datetime import date

        app = self.abrir()
        plan = dict(ciudad="Oporto", total=600, vuelo=200, alojamiento=400,
                    nombre="Hotel guardado", ida_fecha=date(2027, 2, 10),
                    vuelta_fecha=date(2027, 2, 13), ida=[], vuelta=[])
        app.session_state["resultado_con_aprendizaje"] = (
            [plan], ["Traza guardada"], None, 800, "LEN", 2, 100, "ejemplo",
        )
        app.run()
        next(boton for boton in app.button if boton.label.startswith("Guardar esta búsqueda")).click().run()
        with (
            patch("src.interfaz_ofertas.consultar_serpapi") as consultar,
            patch("src.interfaz_ofertas.ClienteOllama") as modelo,
        ):
            app.session_state["apartado_viajesibi"] = "Demostraciones"
            app.run()
            app.radio[0].set_value("Búsquedas guardadas").run()
            consultar.assert_not_called()
            modelo.assert_not_called()
        self.assertFalse(app.exception)
        self.assertFalse(app.text_input)
        self.assertIn("Oporto · 600.00 €", [titulo.value for titulo in app.subheader])
        self.assertIn("Traza guardada", [elemento.value for elemento in app.markdown])

    def test_busqueda_simulada_usa_formulario_y_modelo_sin_serpapi(self):
        app = self.abrir()
        app.session_state["apartado_viajesibi"] = "Demostraciones"
        app.run()
        app.radio[0].set_value("Búsqueda simulada").run()
        app.selectbox[0].set_value("VLC")
        app.multiselect[1].set_value(["Hostales y albergues"])
        next(campo for campo in app.number_input if campo.label.startswith("Presupuesto por persona")).set_value(1000)
        with (
            patch("src.interfaz_ofertas.consultar_serpapi") as consultar,
            patch("src.agent.ClienteOllama.consultar_json",
                  side_effect=modelo_equipo) as modelo,
        ):
            app.button[0].click().run()
            consultar.assert_not_called()
            self.assertGreaterEqual(modelo.call_count, 4)
        self.assertFalse(app.exception)
        self.assertTrue(any("Hostales y albergues" in elemento.value for elemento in app.markdown))
        self.assertFalse(any(campo.label == "Clave de SerpApi" for campo in app.text_input))

    def test_comparacion_usa_mismo_numero_de_intentos_y_puede_guardarse(self):
        app = self.abrir("clave-ficticia")
        app.session_state["apartado_viajesibi"] = "Comparar IA y agente"
        app.run()
        app.radio[0].set_value("Lista fija y planificador anterior").run()
        app.selectbox[0].set_value("VLC")
        next(campo for campo in app.number_input if campo.label.startswith("Presupuesto por persona")).set_value(100)
        with (
            patch("src.interfaz_ofertas.consultar_serpapi", return_value={}) as api,
            patch("src.agent.ClienteOllama.consultar_json", side_effect=[
                '{"busquedas":[{"aeropuerto":"OPO","fechas":0},{"aeropuerto":"PRG","fechas":0}]}',
                '{"accion":"consultar","aeropuerto":"LIS","fechas":0,"motivo":"buscar_disponibilidad"}',
            ]),
        ):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(api.call_count, 3)
        comparacion, _, _ = app.session_state["comparacion_real"]
        self.assertEqual([[i["aeropuerto"] for i in fila[1]] for fila in comparacion],
                         [["OPO", "PRG"], ["OPO", "LIS"]])

        next(boton for boton in app.button if boton.label == "Guardar esta comparación").click().run()
        app.session_state["apartado_viajesibi"] = "Demostraciones"
        app.run()
        app.radio[0].set_value("Comparaciones guardadas").run()
        self.assertFalse(app.exception)
        self.assertTrue(app.table)

    def test_comparacion_real_reutiliza_la_consulta_del_primer_destino(self):
        app = self.abrir("clave-ficticia")
        app.session_state["apartado_viajesibi"] = "Comparar IA y agente"
        app.run()
        app.radio[0].set_value("Lista fija y planificador anterior").run()
        app.selectbox[0].set_value("VLC")
        with (
            patch("src.interfaz_ofertas.consultar_serpapi", return_value={}) as api,
            patch("src.agent.ClienteOllama.consultar_json", side_effect=[
                '{"busquedas":[{"aeropuerto":"OPO","fechas":0},{"aeropuerto":"PRG","fechas":0}]}',
                '{"accion":"consultar","aeropuerto":"LIS","fechas":0,"motivo":"buscar_disponibilidad"}',
            ]),
        ):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertIn("Comparación con ofertas reales", [titulo.value for titulo in app.subheader])
        self.assertEqual([llamada.args[1]["arrival_id"] for llamada in api.call_args_list],
                         ["OPO", "PRG", "LIS"])

    def test_comparacion_simulada_separada_y_sin_api(self):
        app = self.abrir()
        app.session_state["apartado_viajesibi"] = "Demostraciones"
        app.run()
        app.radio[0].set_value("Comparación simulada").run()
        app.radio[1].set_value("Lista fija y planificador anterior").run()
        app.selectbox[0].set_value("VLC")
        with (
            patch("src.interfaz_ofertas.consultar_serpapi") as api,
            patch("src.agent.ClienteOllama.consultar_json", side_effect=[
                '{"busquedas":[{"aeropuerto":"OPO","fechas":0},{"aeropuerto":"PRG","fechas":0}]}',
                '{"accion":"consultar","aeropuerto":"LIS","fechas":0,"motivo":"comparar_total"}',
            ]),
        ):
            next(b for b in app.button if b.label == "Comparar estrategias").click().run()
        api.assert_not_called()
        self.assertFalse(app.exception)
        self.assertIn("comparacion_simulada", app.session_state)
        self.assertNotIn("comparacion_real", app.session_state)
        self.assertIn("Cómo cambió la búsqueda del agente", [h.value for h in app.subheader])
        self.assertFalse(any(c.label == "Clave de SerpApi" for c in app.text_input))
        self.assertTrue(app.checkbox[0].disabled)

    def test_comparacion_explica_resultado_economico_antes_del_detalle(self):
        app = self.abrir("clave-ficticia")
        app.session_state["apartado_viajesibi"] = "Comparar IA y agente"
        app.run()
        app.radio[0].set_value("Lista fija y planificador anterior").run()
        intento = dict(aeropuerto="OPO", ida="2027-02-01", vuelta="2027-02-04",
                       total=900, vuelo=500, alojamiento=400, consultas_proveedor=3)
        app.session_state["comparacion_real"] = (
            [("Lista fija", [intento], [{"total": 900}], []),
             ("Agente adaptativo", [dict(intento, total=850)], [{"total": 850}], [])], 800, "prueba-balance")
        app.run()
        self.assertFalse(app.exception)
        self.assertIn("¿Qué consiguió cada método?", [h.value for h in app.subheader])
        self.assertIn("Ninguno consiguió un viaje con total confirmado dentro del presupuesto.",
                      [e.value for e in app.info])

    def test_laboratorio_visible_sin_api_y_con_experiencia_persistente_vacia(self):
        app = self.abrir()
        app.session_state["apartado_viajesibi"] = "Aprendizaje"
        with patch("src.interfaz_ofertas.consultar_serpapi") as api, patch("src.agent.ClienteOllama.consultar_json") as modelo:
            app.run()
            api.assert_not_called()
            modelo.assert_not_called()
        self.assertFalse(app.exception)
        self.assertIn("Aprender de la experiencia", [h.value for h in app.header])
        boton = next(b for b in app.button if b.label.startswith("Proponer una mejora"))
        self.assertTrue(boton.disabled)

    def test_defensa_muestra_roles_e_informes_sin_consumir_api(self):
        app = self.abrir()
        app.session_state["apartado_viajesibi"] = "Demostraciones"
        app.run()
        with patch("src.agent.ClienteOllama.consultar_json") as modelo, \
             patch("src.interfaz_ofertas.consultar_serpapi") as api:
            app.radio[0].set_value("Defender el proyecto").run()
        self.assertFalse(app.exception)
        modelo.assert_not_called()
        api.assert_not_called()
        self.assertTrue(any("Quién hace cada trabajo" in s.value for s in app.subheader))
        self.assertTrue(any("Informe del piloto" == s.label for s in app.selectbox))

    def test_informe_aprobado_muestra_ahorro_medido_y_coste_de_validar(self):
        pares = []
        for dia in (15,22):
            base = dict(ida=f"2027-02-{dia}", viaje_encontrado=True, total=480,
                        consultas=8, llamadas_modelo=2, segundos=10)
            pares.append(dict(sin_memoria=base, con_memoria=dict(base, consultas=4, llamadas_modelo=1)))
        informe = dict(propuesta={"hipotesis":"Priorizar éxitos repetidos"}, validacion=pares,
                       adoptada=True, motivo_validacion="Mejora comprobada")
        app = AppTest.from_string("from src.interfaz_aprendizaje import mostrar_informe\n"
                                  + f"mostrar_informe({informe!r})").run()
        self.assertFalse(app.exception)
        self.assertTrue(any("16 → 8" in i.value for i in app.info))
        self.assertTrue(any("24 consultas" in c.value for c in app.caption))

    def test_comparacion_nueva_muestra_resultados_del_equipo(self):
        import json

        app = self.abrir()
        app.session_state["apartado_viajesibi"] = "Demostraciones"
        app.run()
        app.radio[0].set_value("Comparación simulada").run()
        app.selectbox[0].set_value("VLC")

        def modelo(mensajes, formato):
            if "busquedas" in formato["properties"]:
                return '{"busquedas":[{"aeropuerto":"MAD","fechas":0},{"aeropuerto":"OPO","fechas":0}]}'
            if "motivo" in formato["properties"]:
                return '{"accion":"seguir_lista","aeropuerto":"LIS","fechas":0,"motivo":"mantener_plan"}'
            return modelo_equipo(mensajes, formato)

        with patch("src.agent.ClienteOllama.consultar_json", side_effect=modelo):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertIn("comparacion_simulada_equipo", app.session_state)
        self.assertTrue(app.table)
        resultados = app.session_state["comparacion_simulada_equipo"][0]
        self.assertEqual(resultados[1][0], "Equipo de cuatro agentes")
