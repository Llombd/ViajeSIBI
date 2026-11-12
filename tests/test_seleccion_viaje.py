from datetime import date
import json
import unittest
from unittest.mock import Mock, patch

from src.ofertas_reales import ErrorConsultaOfertas
from src.seleccion_viaje import explorar_ofertas, intervalos, proponer_busquedas


class TestSeleccionViaje(unittest.TestCase):
    def test_ventana_flexible_respeta_noches_y_limites(self):
        self.assertEqual(intervalos(date(2027, 2, 10), date(2027, 2, 16), 3), [
            (date(2027, 2, 10), date(2027, 2, 13)),
            (date(2027, 2, 11), date(2027, 2, 14)),
            (date(2027, 2, 13), date(2027, 2, 16)),
        ])
        self.assertEqual(intervalos(date(2027, 2, 10), date(2027, 2, 11), 3), [])

    def test_qwen_elige_destinos_sin_aceptar_codigos_o_fechas_invalidos(self):
        fechas = intervalos(date(2027, 2, 10), date(2027, 2, 16), 3)
        cliente = Mock()
        cliente.consultar_json.return_value = json.dumps({"busquedas": [
            {"aeropuerto": "VLC", "fechas": 0},
            {"aeropuerto": "XYZ", "fechas": 0},
            {"aeropuerto": "LIS", "fechas": 3},
            {"aeropuerto": "OPO", "fechas": 1},
            {"aeropuerto": "OPO", "fechas": 0},
            {"aeropuerto": "PRG", "fechas": 2},
        ]})
        self.assertEqual(proponer_busquedas(cliente, "VLC", fechas, "cerveza artesanal", 2, 800),
                         [("OPO", fechas[1]), ("PRG", fechas[2])])
        solicitud = cliente.consultar_json.call_args.args[0][-1]["content"]
        self.assertIn("cerveza artesanal", solicitud)
        self.assertIn('"presupuesto_eur": 800', solicitud)

    def test_sigue_al_siguiente_destino_y_ordena_ofertas(self):
        fecha = (date(2027, 2, 10), date(2027, 2, 13))
        with patch("src.seleccion_viaje.buscar_planes", side_effect=[
            ([], []), ([{"total": 750, "vuelo": 300, "alojamiento": 450}], []), ([{"total": 600, "vuelo": 300, "alojamiento": 300}], []),
        ]) as buscar:
            planes, registro, primer_total = explorar_ofertas(Mock(), "VLC", [
                ("OPO", fecha), ("LIS", fecha), ("PRG", fecha),
            ], 2, 800)
        self.assertEqual(buscar.call_count, 3)
        self.assertEqual([plan["total"] for plan in planes], [600, 750])
        self.assertIn("Oporto", registro[0])
        self.assertIsNone(primer_total)

    def test_conserva_coste_de_primera_propuesta_para_comparar(self):
        fecha = (date(2027, 2, 10), date(2027, 2, 13))
        with patch("src.seleccion_viaje.buscar_planes", side_effect=[
            ([{"total": 750, "vuelo": 300, "alojamiento": 450}], []), ([{"total": 600, "vuelo": 300, "alojamiento": 300}], []),
        ]):
            planes, _, primer_total = explorar_ofertas(Mock(), "VLC", [
                ("OPO", fecha), ("LIS", fecha),
            ], 2, 800)
        self.assertEqual(primer_total - planes[0]["total"], 150)

    def test_una_consulta_fallida_no_descarta_otra_propuesta(self):
        fecha = (date(2027, 2, 10), date(2027, 2, 13))
        with patch("src.seleccion_viaje.buscar_planes", side_effect=[
            ErrorConsultaOfertas("Consulta sin verificar"), ([{"total": 600, "vuelo": 300, "alojamiento": 300}], []),
        ]):
            planes, registro, _ = explorar_ofertas(Mock(), "VLC", [
                ("OPO", fecha), ("LIS", fecha),
            ], 2, 800)
        self.assertEqual([plan["total"] for plan in planes], [600])
        self.assertIn("Consulta sin verificar", registro)

    def test_replantea_con_costes_observados_y_encuentra_otra_combinacion(self):
        fecha = (date(2027, 2, 10), date(2027, 2, 13))
        replantear = Mock(return_value=[("LIS", fecha)])
        with patch("src.seleccion_viaje.buscar_planes", side_effect=[
            ([{"total": 900, "vuelo": 200, "alojamiento": 700}], []),
            ([{"total": 650, "vuelo": 350, "alojamiento": 300}], []),
        ]) as buscar:
            planes, registro, primer_total = explorar_ofertas(
                Mock(), "VLC", [("OPO", fecha), ("PRG", fecha)], 2, 800, replantear,
            )
        self.assertEqual({k: replantear.call_args.args[0][0][k] for k in ("aeropuerto", "ida", "vuelta", "total", "vuelo", "alojamiento", "impuestos_confirmados")},
                         {"aeropuerto": "OPO", "ida": "2027-02-10", "vuelta": "2027-02-13",
                          "total": 900, "vuelo": 200, "alojamiento": 700, "impuestos_confirmados": True})
        self.assertEqual([llamada.args[2] for llamada in buscar.call_args_list], ["OPO", "LIS"])
        self.assertEqual([plan["total"] for plan in planes], [650, 900])
        self.assertEqual(primer_total, 900)
        self.assertTrue(any("tras revisar los resultados" in paso for paso in registro))

    def test_no_inventa_alternativas_si_el_modelo_solo_repite(self):
        primera = (date(2027, 2, 10), date(2027, 2, 13))
        segunda = (date(2027, 2, 11), date(2027, 2, 14))
        replantear = Mock(return_value=[("OPO", primera)])
        with patch("src.seleccion_viaje.buscar_planes", return_value=([], [])) as buscar:
            planes, _, _ = explorar_ofertas(Mock(), "LEN", [("OPO", primera)], 2, 800,
                                              replantear, (primera, segunda))
        consultas = [(llamada.args[2], llamada.args[4]) for llamada in buscar.call_args_list]
        self.assertEqual(len(set(consultas)), 1)
        self.assertEqual(planes, [])

    def test_alternativas_prueban_aeropuertos_antes_de_relajar_gustos(self):
        from src.seleccion_viaje import planificar_con_alternativas

        fecha = (date(2027, 2, 10), date(2027, 2, 13))
        viable = {"total": 550, "vuelo": 200, "alojamiento": 350}
        with (
            patch("src.seleccion_viaje.proponer_busquedas", return_value=[("OPO", fecha)]) as proponer,
            patch("src.seleccion_viaje.explorar_ofertas", side_effect=[
                ([], [], None), ([], [], None), ([], [], None), ([viable], [], 550),
            ]),
        ):
            planes, _, _ = planificar_con_alternativas(
                Mock(), Mock(), "LEN", [fecha], "cultura, playa", 2, 578,
            )
        self.assertEqual([(llamada.args[1], llamada.args[3]) for llamada in proponer.call_args_list],
                         [("LEN", "cultura, playa"), ("VLL", "cultura, playa"),
                          ("MAD", "cultura, playa"), ("LEN", "cultura")])
        self.assertEqual(planes[0]["preferencias_omitidas"], ("playa",))
        self.assertEqual(planes[0]["salida"], "LEN")

    def test_margen_conserva_origen_y_preferencias(self):
        from src.seleccion_viaje import planificar_con_alternativas

        fecha = (date(2027, 2, 10), date(2027, 2, 13))
        plan = {"total": 650, "vuelo": 300, "alojamiento": 350}
        with (
            patch("src.seleccion_viaje.proponer_busquedas", return_value=[("OPO", fecha)]) as proponer,
            patch("src.seleccion_viaje.explorar_ofertas", return_value=([plan], [], 650)),
        ):
            planes, registro, _ = planificar_con_alternativas(
                Mock(), Mock(), "LEN", [fecha], "playa", 2, 578, margen=100,
            )
        self.assertEqual(proponer.call_count, 1)
        self.assertEqual(planes[0]["salida"], "LEN")
        self.assertEqual(planes[0]["preferencias_omitidas"], ())
        self.assertIn("dentro del margen", registro[-1])

    def test_comparacion_controlada_con_mismo_numero_de_consultas(self):
        fecha = (date(2027, 2, 10), date(2027, 2, 13))
        ofertas = {
            "OPO": {"total": 900, "vuelo": 200, "alojamiento": 700},
            "PRG": {"total": 850, "vuelo": 250, "alojamiento": 600},
            "LIS": {"total": 650, "vuelo": 350, "alojamiento": 300},
        }

        def consultar_plan(consultar, origen, destino, ciudad, ida, vuelta, adultos, presupuesto, **kwargs):
            return [ofertas[destino]], []

        propuestas = [("OPO", fecha), ("PRG", fecha)]
        with patch("src.seleccion_viaje.buscar_planes", side_effect=consultar_plan) as buscar:
            fijos, _, _ = explorar_ofertas(Mock(), "VLC", propuestas, 2, 800)
            consultas_fijas = buscar.call_count
            buscar.reset_mock()
            adaptados, _, _ = explorar_ofertas(
                Mock(), "VLC", propuestas, 2, 800, lambda _: [("LIS", fecha)],
            )
            self.assertEqual(buscar.call_count, consultas_fijas)
        self.assertGreater(fijos[0]["total"], 800)
        self.assertEqual(adaptados[0]["total"], 650)

    def test_comparacion_no_cambia_fechas_por_su_cuenta(self):
        primera = (date(2027, 1, 1), date(2027, 1, 4))
        segunda = (date(2027, 1, 15), date(2027, 1, 18))
        propuestas = [("OPO", primera), ("LIS", primera)]
        with patch("src.seleccion_viaje.buscar_planes", return_value=([], [])) as consultar:
            _, traza, _ = explorar_ofertas(
                Mock(), "LEN", propuestas, 2, 400, replantear=lambda _: [propuestas[1]],
                fechas=[primera, segunda], limite_intentos=2, conservar_pendientes=True,
            )
        self.assertEqual([(c.args[2], c.args[4]) for c in consultar.call_args_list],
                         [("OPO", primera[0]), ("LIS", primera[0])])
        self.assertFalse(any("otras fechas permitidas" in paso for paso in traza))

    def test_balance_distingue_ganador_empate_y_precios_sin_confirmar(self):
        from src.seleccion_viaje import evaluar_comparacion

        intentos = [{}, {}]
        fija = ("Lista fija", intentos, [{"total": 850}], [])
        for plan, esperado in (
            ({"total": 650}, "Gana el agente"),
            ({"total": 850}, "Empate"),
            ({"total": 900}, "Gana la lista fija"),
            ({"total": 650, "impuestos_confirmados": False}, "Sin datos suficientes"),
        ):
            with self.subTest(plan=plan):
                adaptativa = ("Agente", intentos, [plan], [])
                self.assertEqual(evaluar_comparacion([fija, adaptativa]), esperado)
