"""Colaboración con modelos y herramientas controlados, sin cuota de SerpApi."""
from datetime import date
import json
import unittest
from unittest.mock import Mock

from src.demo_ofertas import consultar_catalogo_ficticio
from src.equipo_viaje import EquipoViaje


def modelo_equipo(mensajes, formato):
    acciones = formato["properties"]["accion"]["enum"]
    rol = mensajes[0]["content"]
    if "agente de Destinos" in rol:
        accion = next((a for a in acciones if a.startswith("OPO:")), acciones[0])
    elif "agente de Coordinación" in rol:
        accion = next((a for a in ("transporte", "alojamiento", "destino") if a in acciones), "terminar")
    else:
        accion = "terminar" if "terminar" in acciones else acciones[0]
    return json.dumps({"accion": accion})


class TestEquipoViaje(unittest.TestCase):
    def test_cuatro_roles_consultan_ofertas_y_comparten_costes(self):
        cliente = Mock()
        cliente.consultar_json.side_effect = modelo_equipo
        equipo = EquipoViaje(cliente, consultar_catalogo_ficticio)
        planes, traza, _ = equipo.planificar(
            "VLC", [(date(2027, 2, 1), date(2027, 2, 4))], "cultura", 2, 2000, objetivo=1,
        )
        self.assertTrue(planes)
        self.assertEqual(planes[0]["total"], planes[0]["vuelo"] + planes[0]["alojamiento"])
        roles = {llamada.args[0][0]["content"].split(".")[0] for llamada in cliente.consultar_json.call_args_list}
        self.assertEqual(len(roles), 4)
        self.assertTrue(any("Alojamiento → Coordinación" in paso for paso in traza))
        self.assertLessEqual(equipo.consultas, 12)

    def test_recupera_viaje_al_cambiar_destino_por_alojamiento_caro(self):
        decisiones = iter([
            "destino", "OPO:0", "transporte", "2", "0",
            "alojamiento", "3", "destino", "LIS:0",
            "transporte", "2", "0", "alojamiento", "3", "terminar",
        ])
        cliente = Mock()

        def modelo(mensajes, formato):
            accion = next(decisiones)
            self.assertIn(accion, formato["properties"]["accion"]["enum"])
            if accion == "destino" and '"total": 900' in mensajes[-1]["content"]:
                self.assertNotIn("terminar", formato["properties"]["accion"]["enum"])
            return json.dumps({"accion": accion})

        cliente.consultar_json.side_effect = modelo

        def ofertas(parametros):
            datos = consultar_catalogo_ficticio(parametros)
            if parametros["engine"] == "google_hotels":
                coste = 700 if parametros["q"].startswith("Oporto") else 300
                return {"properties": [{"name": "Estancia", "total_rate": {"extracted_after_taxes_fees": coste}}]}
            if "departure_token" in parametros:
                coste = 200 if parametros["arrival_id"] == "OPO" else 350
                for vuelo in datos["best_flights"]:
                    vuelo["price"] = coste
            return datos

        equipo = EquipoViaje(cliente, ofertas)
        planes, _, _ = equipo.planificar(
            "VLC", [(date(2027, 2, 1), date(2027, 2, 4))], "cultura", 2, 800, objetivo=1,
        )
        self.assertEqual([p["total"] for p in planes], [650, 900])
        memoria_destinos = equipo.destinos.historial[-2]["content"]
        self.assertIn('"alojamiento_minimo": 700', memoria_destinos)
        self.assertIn('"total": 900', memoria_destinos)

    def test_accion_invalida_cierra_sin_ejecutar_herramientas(self):
        cliente = Mock()
        cliente.consultar_json.return_value = '{"accion":"inventada"}'
        proveedor = Mock()
        planes, traza, _ = EquipoViaje(cliente, proveedor).planificar(
            "VLC", [(date(2027, 2, 1), date(2027, 2, 4))], "", 2, 800,
        )
        self.assertEqual(planes, [])
        proveedor.assert_not_called()
        self.assertTrue(any("inválida" in p for p in traza))

    def test_tope_global_de_consultas_se_respeta_sin_inventar_precios(self):
        cliente = Mock()
        cliente.consultar_json.side_effect = modelo_equipo
        proveedor = Mock(side_effect=consultar_catalogo_ficticio)
        equipo = EquipoViaje(cliente, proveedor, max_consultas=2)
        planes, traza, _ = equipo.planificar(
            "VLC", [(date(2027, 2, 1), date(2027, 2, 4))], "", 2, 800,
        )
        self.assertLessEqual(proveedor.call_count, 2)
        self.assertEqual(planes, [])
        self.assertTrue(any("consultas de datos" in paso for paso in traza))

    def test_revisa_estancia_del_mismo_destino_y_conserva_vuelo(self):
        decisiones = iter([
            "destino", "OPO:0", "transporte", "2", "0",
            "alojamiento", "8", "alojamiento", "3", "terminar",
        ])
        cliente = Mock()
        cliente.consultar_json.side_effect = lambda mensajes, formato: json.dumps({"accion": next(decisiones)})
        consultas = []

        def proveedor(parametros):
            consultas.append(parametros)
            datos = consultar_catalogo_ficticio(parametros)
            if parametros["engine"] == "google_hotels":
                importe = 700 if parametros["sort_by"] == 8 else 300
                return {"properties": [{"name": "Hotel comprobado",
                                       "total_rate": {"extracted_after_taxes_fees": importe}}]}
            if "departure_token" in parametros:
                for vuelo in datos["best_flights"]:
                    vuelo["price"] = 200
            return datos

        equipo = EquipoViaje(cliente, proveedor)
        planes, traza, _ = equipo.planificar(
            "VLC", [(date(2027, 2, 1), date(2027, 2, 4))], "", 2, 800, objetivo=1,
        )
        self.assertEqual([p["total"] for p in planes], [500])
        self.assertEqual([p["sort_by"] for p in consultas if p["engine"] == "google_hotels"], [8, 3])
        self.assertEqual(sum(p["engine"] == "google_flights" for p in consultas), 2)
        self.assertTrue(any("Revisar otras estancias" in paso for paso in traza))

    def test_revisa_vuelos_del_mismo_destino_y_conserva_estancia(self):
        decisiones = iter([
            "destino", "OPO:0", "transporte", "5", "0",
            "alojamiento", "3", "transporte", "2", "0", "terminar",
        ])
        cliente = Mock()
        cliente.consultar_json.side_effect = lambda mensajes, formato: json.dumps({"accion": next(decisiones)})
        consultas = []

        def proveedor(parametros):
            consultas.append(parametros)
            datos = consultar_catalogo_ficticio(parametros)
            if parametros["engine"] == "google_hotels":
                return {"properties": [{"name": "Hotel comprobado",
                                       "total_rate": {"extracted_after_taxes_fees": 400}}]}
            if "departure_token" in parametros:
                for vuelo in datos["best_flights"]:
                    vuelo["price"] = 400 if parametros["sort_by"] == 5 else 250
            return datos

        equipo = EquipoViaje(cliente, proveedor)
        planes, traza, _ = equipo.planificar(
            "VLC", [(date(2027, 2, 1), date(2027, 2, 4))], "", 2, 750, objetivo=1,
        )
        self.assertEqual([p["total"] for p in planes], [650])
        self.assertEqual(sum(p["engine"] == "google_hotels" for p in consultas), 1)
        self.assertTrue(any("Revisar transporte" in paso for paso in traza))

    def test_repite_destino_en_otras_fechas_permitidas(self):
        decisiones = iter([
            "destino", "OPO:0", "transporte", "2", "0",
            "alojamiento", "3", "destino", "OPO:1",
            "transporte", "2", "0", "alojamiento", "3", "terminar",
        ])
        cliente = Mock()
        cliente.consultar_json.side_effect = lambda mensajes, formato: json.dumps({"accion": next(decisiones)})

        def proveedor(parametros):
            datos = consultar_catalogo_ficticio(parametros)
            if parametros["engine"] == "google_hotels":
                importe = 700 if parametros["check_in_date"] == "2027-02-01" else 300
                return {"properties": [{"name": "Hotel comprobado",
                                       "total_rate": {"extracted_after_taxes_fees": importe}}]}
            if "departure_token" in parametros:
                for vuelo in datos["best_flights"]:
                    vuelo["price"] = 200
            return datos

        equipo = EquipoViaje(cliente, proveedor)
        planes, _, _ = equipo.planificar(
            "VLC", [(date(2027, 2, 1), date(2027, 2, 4)),
                    (date(2027, 2, 8), date(2027, 2, 11))], "", 2, 800, objetivo=1,
        )
        self.assertEqual([p["total"] for p in planes], [500, 900])
        self.assertEqual(planes[0]["ida_fecha"], date(2027, 2, 8))
        self.assertEqual({p["aeropuerto"] for p in planes}, {"OPO"})

    def test_coordinador_puede_pedir_alojamiento_antes_de_vuelos(self):
        decisiones = iter([
            "destino", "OPO:0", "alojamiento", "3",
            "transporte", "2", "0", "terminar",
        ])
        cliente = Mock()
        cliente.consultar_json.side_effect = lambda mensajes, formato: json.dumps({"accion": next(decisiones)})
        proveedor = Mock(side_effect=consultar_catalogo_ficticio)
        planes, _, _ = EquipoViaje(cliente, proveedor).planificar(
            "VLC", [(date(2027, 2, 1), date(2027, 2, 4))], "", 2, 2000, objetivo=1,
        )
        self.assertTrue(planes)
        self.assertEqual(proveedor.call_args_list[0].args[0]["engine"], "google_hotels")

    def test_especialista_devuelve_resultado_antes_de_gastar_otra_consulta(self):
        cliente = Mock()
        cliente.consultar_json.return_value = '{"accion":"3"}'
        proveedor = Mock(return_value={"properties": [
            {"name": "Hotel", "total_rate": {"extracted_after_taxes_fees": 250}},
        ]})
        equipo = EquipoViaje(cliente, proveedor)
        estado = {"alojamientos": [], "ordenes_estancias": {"3": "Precio", "8": "Valoración"}}
        ofertas = equipo.buscar_estancias({"engine": "google_hotels"}, {}, 300, estado)
        self.assertEqual(len(ofertas), 1)
        self.assertEqual(proveedor.call_count, 1)
        self.assertEqual(cliente.consultar_json.call_count, 1)
        self.assertEqual(estado["ordenes_estancias"], {"8": "Valoración"})

    def test_experiencia_validada_prioriza_candidatos_sin_usar_precios_antiguos(self):
        llamadas = []

        def modelo(mensajes, formato):
            acciones = formato["properties"]["accion"]["enum"]
            llamadas.append(mensajes)
            return json.dumps({"accion": acciones[0]})

        cliente = Mock()
        cliente.consultar_json.side_effect = modelo
        equipo = EquipoViaje(cliente, consultar_catalogo_ficticio)
        equipo.planificar(
            "VLC", [(date(2027, 3, 2), date(2027, 3, 5))], "cultura", 2, 800,
            experiencia=[{"aeropuerto": "BCN", "media_historica": 1}],
        )
        self.assertTrue(any("[Destinos] Barcelona" in paso for paso in equipo.registro))
        self.assertGreater(equipo.consultas, 0)
        self.assertTrue(all(" = 1.00 €" not in paso for paso in equipo.registro))
