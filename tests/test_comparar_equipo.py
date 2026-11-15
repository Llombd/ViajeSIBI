"""Comparación del equipo y el planificador con los mismos datos y límites."""
from datetime import date
import json
import unittest

from src.balance_comparacion import medir_resultado
from src.comparar_equipo import comparar_un_agente_y_equipo
from src.demo_ofertas import consultar_catalogo_ficticio
from test_equipo_viaje import modelo_equipo


class ClienteDePrueba:
    def consultar_json(self, mensajes, formato):
        if "busquedas" in formato["properties"]:
            return '{"busquedas":[{"aeropuerto":"MAD","fechas":0},{"aeropuerto":"LIS","fechas":0},{"aeropuerto":"OPO","fechas":0}]}'
        if "motivo" in formato["properties"]:
            return '{"accion":"seguir_lista","aeropuerto":"OPO","fechas":0,"motivo":"mantener_plan"}'
        return modelo_equipo(mensajes, formato)


class TestCompararEquipo(unittest.TestCase):
    def test_compara_resultados_y_cuenta_decisiones_de_los_cuatro_roles(self):
        resultados = comparar_un_agente_y_equipo(
            ClienteDePrueba(), consultar_catalogo_ficticio, "VLC",
            [(date(2027, 3, 2), date(2027, 3, 5))], "cultura", 2, 800,
        )
        self.assertEqual([r[0] for r in resultados],
                         ["Un agente con herramientas", "Equipo de cuatro agentes"])
        for resultado in resultados:
            medicion = medir_resultado(resultado, 800)
            self.assertLessEqual(medicion["consultas"], 12)
            self.assertGreater(medicion["llamadas_modelo"], 0)
            for plan in resultado[2]:
                self.assertEqual(plan["total"], plan["vuelo"] + plan["alojamiento"])
        self.assertTrue(any("[Destinos]" in linea for linea in resultados[1][3]))
