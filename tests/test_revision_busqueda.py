"""Regresiones del ciclo observar, decidir y comprobar; sin API ni Ollama."""
from datetime import date
import json
import unittest
from unittest.mock import Mock, patch

from src.agent import ErrorOllama
from src.seleccion_viaje import (
    DecisionBusqueda, decidir_siguiente_busqueda, diagnosticar, explorar_ofertas,
    comparar_estrategias, evaluar_comparacion, planificar_con_alternativas,
)
from src.ofertas_reales import buscar_planes


class TestRevisionBusqueda(unittest.TestCase):
    fechas = [(date(2027, 2, 1), date(2027, 2, 4)),
              (date(2027, 2, 8), date(2027, 2, 11))]

    def decision(self, respuesta, observaciones=()):
        self.cliente = Mock()
        self.cliente.consultar_json.return_value = json.dumps(respuesta)
        return decidir_siguiente_busqueda(self.cliente, "MAD", self.fechas, "playa", 2, 800, observaciones)

    def test_decision_con_resultados_parciales_y_condiciones_originales(self):
        observacion = dict(aeropuerto="OPO", ida="2027-02-01", vuelta="2027-02-04",
                          diagnostico=dict(estado="sin_alojamiento", vuelo_minimo=200))
        decision = self.decision(dict(accion="consultar", aeropuerto="LIS", fechas=0, motivo="comparar_alojamiento"), [observacion])
        self.assertEqual(decision.consulta, ("LIS", self.fechas[0]))
        datos = json.loads(self.cliente.consultar_json.call_args.args[0][1]["content"])
        self.assertEqual(datos["origen_fijo"], "MAD")
        self.assertEqual(datos["preferencias_que_conservar"], "playa")
        self.assertIn("200.00", datos["resultados"][0]["diagnostico_texto"])

    def test_bloquea_repeticion_origen_fechas_invalidas_y_formato_invalido(self):
        previo = dict(aeropuerto="OPO", ida="2027-02-01", vuelta="2027-02-04")
        base = dict(accion="consultar", aeropuerto="LIS", fechas=0, motivo="comparar_total")
        for cambios in ({"aeropuerto": "MAD"}, {"aeropuerto": "XYZ"}, {"fechas": True},
                        {"fechas": -1}, {"fechas": 2}, {"aeropuerto": "OPO"},
                        {"accion": "subir_presupuesto"}, {"motivo": ""}):
            with self.subTest(cambios=cambios), self.assertRaises(ErrorOllama):
                self.decision({**base, **cambios}, [previo])

    def test_fecha_alternativa_requiere_decision_del_modelo(self):
        decision = self.decision(dict(accion="consultar", aeropuerto="OPO", fechas=1, motivo="buscar_disponibilidad"))
        with patch("src.seleccion_viaje.buscar_planes", return_value=([], [])) as buscar:
            explorar_ofertas(Mock(), "MAD", [("OPO", self.fechas[0])], 2, 800,
                             lambda _: decision, fechas=self.fechas, limite_intentos=2)
        self.assertEqual([c.args[4] for c in buscar.call_args_list], [f[0] for f in self.fechas])

    def test_sin_hotel_conserva_el_precio_del_vuelo_sin_inventar_total(self):
        consultar = Mock(side_effect=[
            {"best_flights": [{"departure_token": "ida", "flights": [
                {"arrival_airport": {"time": "2027-02-01 12:00"}}]}]},
            {"best_flights": [{"price": 200, "flights": [{"flight_number": "TEST"}]}]},
            {"properties": []},
        ])
        diagnostico = {}
        planes, _ = buscar_planes(consultar, "MAD", "OPO", "Oporto", *self.fechas[0],
                                   2, 800, diagnostico=diagnostico)
        self.assertEqual(planes, [])
        self.assertEqual(diagnostico["vuelo_minimo"], 200)
        self.assertEqual(diagnostico["estado"], "sin_alojamiento")
        self.assertNotIn("total", diagnostico)

    def test_diagnostico_no_confunde_error_con_ausencia_ni_impuestos_con_precio_final(self):
        self.assertIn("falló", diagnosticar({"diagnostico": {"estado": "error_consulta"}}, 800))
        mensaje = diagnosticar(dict(total=900, vuelo=200, alojamiento=700, impuestos_confirmados=False), 800)
        self.assertIn("alojamiento", mensaje)
        self.assertIn("100.00", mensaje)
        self.assertIn("no es un total definitivo", mensaje)

    def test_conserva_plan_valido_si_nueva_decision_empeora(self):
        plan = dict(total=600, vuelo=200, alojamiento=400)
        with patch("src.seleccion_viaje.buscar_planes", side_effect=[([plan], []), ([], [])]):
            planes, _, _ = explorar_ofertas(Mock(), "MAD", [("OPO", self.fechas[0])], 2, 800,
                                            lambda _: DecisionBusqueda(("LIS", self.fechas[0]), "Comparar"),
                                            limite_intentos=2)
        self.assertEqual(planes[0]["total"], 600)

    def test_una_etapa_limitada_no_consume_tres_intentos(self):
        with (patch("src.seleccion_viaje.proponer_busquedas", return_value=[("OPO", self.fechas[0])]),
              patch("src.seleccion_viaje.explorar_ofertas", return_value=([], [], None)) as explorar):
            planificar_con_alternativas(Mock(), Mock(), "LEN", self.fechas, "", 2, 800)
        self.assertEqual([c.kwargs["limite_intentos"] for c in explorar.call_args_list], [3, 1, 1])

    def test_comparacion_demuestra_recuperacion_con_decision_y_datos_simulados(self):
        cliente = Mock()
        cliente.consultar_json.side_effect = [
            json.dumps({"busquedas": [{"aeropuerto": c, "fechas": 0} for c in ("OPO", "PRG")]}),
            json.dumps(dict(accion="consultar", aeropuerto="LIS", fechas=0, motivo="comparar_alojamiento")),
        ]
        def ofertas(consultar, origen, destino, *args, **kwargs):
            vuelo, hotel = {"OPO": (200, 700), "PRG": (250, 600), "LIS": (350, 300)}[destino]
            return [dict(vuelo=vuelo, alojamiento=hotel, total=vuelo+hotel)], []
        with patch("src.seleccion_viaje.buscar_planes", side_effect=ofertas):
            resultados = comparar_estrategias(cliente, Mock(), "MAD", self.fechas, "cultura", 2, 800)
        self.assertEqual(evaluar_comparacion(resultados), "Gana el agente")
        self.assertEqual([len(r[1]) for r in resultados], [2, 2])
        observado = resultados[1][1][0]
        self.assertEqual(observado["total"], 900)
        self.assertIn("Lisboa", observado["siguiente_decision"])
        self.assertTrue(any("Objetivo elegido" in t for t in resultados[1][3]))

    def test_llamadas_proveedor_contadas_y_limite_sin_falsa_conclusion(self):
        consultar = Mock(return_value={})
        observaciones = []
        _, traza, _ = explorar_ofertas(consultar, "MAD", [("OPO", self.fechas[0])], 2, 800,
                                      observaciones=observaciones, limite_intentos=1)
        self.assertEqual(observaciones[0]["consultas_proveedor"], 1)
        self.assertIn("no permite concluir", traza[-1])

    def test_invalidacion_conserva_pendientes_y_no_reintenta_modelo_en_bucle(self):
        revisar = Mock(side_effect=ErrorOllama("Formato inválido"))
        consultar = Mock(return_value={})
        observaciones = []
        explorar_ofertas(consultar, "MAD", [("OPO", self.fechas[0]), ("LIS", self.fechas[0])],
                         2, 800, revisar, observaciones=observaciones, limite_intentos=2)
        self.assertEqual([o["aeropuerto"] for o in observaciones], ["OPO", "LIS"])
        self.assertEqual(revisar.call_count, 1)

    def test_no_muestra_razonamiento_libre_con_precios_inventados(self):
        with self.assertRaises(ErrorOllama):
            self.decision(dict(accion="consultar", aeropuerto="LIS", fechas=0, motivo="480 EUR está dentro de 400 EUR"))

    def test_no_repite_consultas_de_etapas_anteriores(self):
        observaciones = [dict(aeropuerto="OPO", ida="2027-02-01", vuelta="2027-02-04")]
        consultar = Mock(return_value={})
        explorar_ofertas(consultar, "MAD", [("OPO", self.fechas[0]), ("LIS", self.fechas[0])],
                         2, 800, fechas=self.fechas, observaciones=observaciones)
        self.assertEqual(consultar.call_count, 1)
        self.assertEqual(consultar.call_args.args[0]["arrival_id"], "LIS")

    def test_recuperacion_completa_tras_descartar_vuelo_sin_gastar_consulta_de_hotel(self):
        from src.balance_comparacion import balance_comparacion

        cliente = Mock()
        def modelo(mensajes, esquema):
            if "busquedas" in esquema["properties"]:
                return json.dumps({"busquedas": [{"aeropuerto": c, "fechas": 0} for c in ("OPO", "PRG")]})
            datos = json.loads(mensajes[-1]["content"])
            self.assertEqual(datos["resultados"][0]["diagnostico"]["estado"], "vuelo_supera_maximo")
            self.assertEqual(datos["resultados"][0]["diagnostico"]["vuelo_minimo"], 950)
            return json.dumps(dict(accion="consultar", aeropuerto="LIS", fechas=0, motivo="comparar_transporte"))
        cliente.consultar_json.side_effect = modelo
        peticiones_hotel = []
        def proveedor(parametros):
            if parametros["engine"] == "google_hotels":
                peticiones_hotel.append(parametros["q"])
                return {"properties": [{"name": "Hotel ficticio", "total_rate": {"extracted_after_taxes_fees": 300}}]}
            if "departure_token" not in parametros:
                return {"best_flights": [{"departure_token": "ida", "flights": [
                    {"arrival_airport": {"time": "2027-02-01 12:00"}}]}]}
            return {"best_flights": [{"price": {"OPO": 950, "PRG": 850, "LIS": 350}[parametros["arrival_id"]],
                                      "flights": [{"flight_number": "TEST"}]}]}
        resultado = comparar_estrategias(cliente, proveedor, "MAD", self.fechas, "cultura", 2, 800)
        self.assertEqual(peticiones_hotel, ["Lisboa, Portugal"])
        balance = balance_comparacion(resultado, 800)
        self.assertEqual(balance["categoria"], "Solo el agente consiguió un viaje")
        self.assertEqual([m["consultas"] for m in balance["metodos"]], [4, 5])
        self.assertEqual(resultado[1][2][0]["total"], 650)

    def test_ahorro_consultas_se_aplica_tambien_a_lista_fija(self):
        from src.demo_ofertas import consultar_catalogo_ficticio
        propuestas = [("OPO", self.fechas[0]), ("LIS", self.fechas[0])]
        sin_limite = Mock(side_effect=consultar_catalogo_ficticio)
        con_limite = Mock(side_effect=consultar_catalogo_ficticio)
        planes, _, _ = explorar_ofertas(sin_limite, "MAD", propuestas, 2, 200)
        observaciones = []
        descartados, _, _ = explorar_ofertas(con_limite, "MAD", propuestas, 2, 200,
                                             limite_total=200, observaciones=observaciones)
        self.assertTrue(all(p["total"] > 200 for p in planes))
        self.assertEqual(descartados, [])
        self.assertEqual((sin_limite.call_count, con_limite.call_count), (8, 6))
        self.assertEqual(sum(o["diagnostico"]["consultas_hotel_evitadas"] for o in observaciones), 2)

    def test_esquema_no_ofrece_combinaciones_repetidas(self):
        previo = dict(aeropuerto="OPO", ida="2027-02-01", vuelta="2027-02-04")
        self.decision(dict(accion="consultar", aeropuerto="OPO", fechas=1, motivo="buscar_disponibilidad"), [previo])
        permitidas = json.loads(self.cliente.consultar_json.call_args.args[0][-1]["content"])["consultas_disponibles"]
        self.assertNotIn("OPO:0", permitidas)
        self.assertIn("OPO:1", permitidas)
        self.assertNotIn("MAD:0", permitidas)

    def test_dos_fechas_del_mismo_destino_no_cumplen_objetivo_de_dos_destinos(self):
        plan = dict(total=500, vuelo=200, alojamiento=300, impuestos_confirmados=True)
        propuestas = [("OPO", f) for f in self.fechas] + [("LIS", self.fechas[0])]
        with patch("src.seleccion_viaje.buscar_planes", return_value=([plan], [])) as buscar:
            explorar_ofertas(Mock(), "MAD", propuestas, 2, 800, objetivo_opciones=2)
        self.assertEqual(buscar.call_count, 3)

    def test_revision_fallida_cuenta_como_trabajo_del_modelo(self):
        from src.balance_comparacion import medir_resultado
        observaciones = []
        _, traza, _ = explorar_ofertas(Mock(return_value={}), "MAD",
            [("OPO", self.fechas[0]), ("LIS", self.fechas[0])], 2, 800,
            replantear=Mock(side_effect=ErrorOllama("Error")), observaciones=observaciones, limite_intentos=2)
        medida = medir_resultado(("Agente", observaciones, [], traza), 800)
        self.assertEqual(medida["llamadas_modelo"], 2)
        self.assertEqual(medida["revisiones_invalidas"], 1)

    def test_exploracion_prioriza_pendientes_sin_prohibir_otras_fechas(self):
        cliente = Mock()
        cliente.consultar_json.return_value = '{"accion":"consultar","aeropuerto":"OPO","fechas":1,"motivo":"buscar_disponibilidad"}'
        previo = dict(aeropuerto="OPO", ida="2027-02-01", vuelta="2027-02-04")
        decision = decidir_siguiente_busqueda(cliente, "MAD", self.fechas, "", 2, 800, [previo],
                                             [("OPO",self.fechas[0]), ("LIS",self.fechas[0])])
        opciones = json.loads(cliente.consultar_json.call_args.args[0][-1]["content"])["consultas_disponibles"]
        self.assertEqual(opciones[0], "LIS:0")
        self.assertEqual(decision.consulta, ("OPO",self.fechas[1]))

    def test_con_total_confirmado_explora_otro_destino_y_sin_total_admite_otras_fechas(self):
        previo = dict(aeropuerto="OPO", ida="2027-02-01", vuelta="2027-02-04", total=900,
                      vuelo=200, alojamiento=700, impuestos_confirmados=True)
        with self.assertRaises(ErrorOllama):
            self.decision(dict(accion="consultar", aeropuerto="OPO", fechas=1,
                               motivo="comparar_total"), [previo])
        previo["impuestos_confirmados"] = False
        decision = self.decision(dict(accion="consultar", aeropuerto="OPO", fechas=1,
                                      motivo="buscar_disponibilidad"), [previo])
        self.assertEqual(decision.consulta, ("OPO",self.fechas[1]))
