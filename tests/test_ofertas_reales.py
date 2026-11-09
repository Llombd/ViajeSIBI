from datetime import date
from io import BytesIO
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from src.ofertas_reales import ErrorConsultaOfertas, ErrorOfertas, buscar_planes, consultar_serpapi


class TestOfertasReales(unittest.TestCase):
    def test_consulta_vuelta_y_usa_total_estancia_con_impuestos(self):
        ida = {"arrival_airport": {"time": "2027-02-10 16:00"}}
        vuelta = {"flight_number": "PR123"}
        consultar = Mock(side_effect=[
            {"best_flights": [{"flights": [ida], "price": 20, "departure_token": "ida1"}]},
            {"other_flights": [{"flights": [vuelta], "price": 400}]},
            {"properties": [
                {"name": "Sin total con impuestos", "total_rate": {"extracted_display_price": 5}},
                {"name": "Por encima", "total_rate": {"extracted_after_taxes_fees": 250}},
                {"name": "Dentro del presupuesto", "total_rate": {"extracted_after_taxes_fees": 175}},
            ]},
        ])
        planes, registro = buscar_planes(
            consultar, "VLC", "OPO", "Oporto", date(2027, 2, 10), date(2027, 2, 13), 2, 600,
        )
        self.assertEqual([plan["total"] for plan in planes], [575, 650, 405])
        self.assertFalse(planes[-1]["impuestos_confirmados"])
        self.assertEqual(planes[0]["vuelta"], [vuelta])
        self.assertEqual(consultar.call_args_list[1].args[0]["departure_token"], "ida1")
        self.assertEqual(consultar.call_args_list[2].args[0]["adults"], 2)
        self.assertIn("1 combinaciones", registro[-1])

    def test_sin_vuelo_utilizable_no_consulta_hoteles(self):
        consultar = Mock(return_value={})
        planes, _ = buscar_planes(
            consultar, "VLC", "OPO", "Oporto", date(2027, 2, 10), date(2027, 2, 13), 2, 600,
        )
        self.assertEqual(planes, [])
        self.assertEqual(consultar.call_count, 1)

    def test_conserva_precio_completo_fuera_de_presupuesto(self):
        ida = {"arrival_airport": {"time": "2027-02-10 16:00"}}
        consultar = Mock(side_effect=[
            {"best_flights": [{"flights": [ida], "departure_token": "ida1"}]},
            {"other_flights": [{"flights": [{"flight_number": "PR123"}], "price": 600}]},
            {"properties": [{"name": "Estancia", "total_rate": {"extracted_after_taxes_fees": 100}}]},
        ])
        planes, _ = buscar_planes(
            consultar, "VLC", "OPO", "Oporto", date(2027, 2, 10), date(2027, 2, 13), 2, 600,
        )
        self.assertEqual([plan["total"] for plan in planes], [700])
        self.assertEqual(consultar.call_count, 3)

    def test_respuesta_exitosa_sin_resultados_no_interrumpe_la_busqueda(self):
        datos = {"search_metadata": {"status": "Success"}, "error": "Sin resultados"}
        with patch("src.ofertas_reales.urlopen", return_value=BytesIO(json.dumps(datos).encode())):
            self.assertEqual(consultar_serpapi("clave-de-prueba", {}), {})

    def test_error_de_consulta_es_distinto_de_busqueda_vacia(self):
        datos = {"search_metadata": {"status": "Error"}, "error": "clave-de-prueba"}
        with patch("src.ofertas_reales.urlopen", return_value=BytesIO(json.dumps(datos).encode())):
            with self.assertRaises(ErrorConsultaOfertas) as error:
                consultar_serpapi("clave-de-prueba", {})
        self.assertNotIn("clave-de-prueba", str(error.exception))

    def test_error_de_red_no_expone_clave(self):
        with patch("src.ofertas_reales.urlopen", side_effect=URLError("clave-de-prueba")):
            with self.assertRaises(ErrorOfertas) as error:
                consultar_serpapi("clave-de-prueba", {})
        self.assertNotIn("clave-de-prueba", str(error.exception))
