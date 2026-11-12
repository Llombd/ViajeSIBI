"""Distingue beneficios observables de afirmaciones de superioridad."""
import unittest
from src.balance_comparacion import balance_comparacion, medir_resultado


def fila(total=None, confirmado=True, consultas=3):
    return ("Método", [{"consultas_proveedor": consultas}],
            [] if total is None else [{"total": total, "impuestos_confirmados": confirmado}], [])


class TestBalanceComparacion(unittest.TestCase):
    def test_solo_agente_encuentra_viaje(self):
        b = balance_comparacion([fila(900), fila(650)], 800)
        self.assertEqual(b["categoria"], "Solo el agente consiguió un viaje")
        self.assertIsNone(b["ahorro"])  # No era un viaje aceptable que el usuario fuese a comprar.

    def test_menor_precio_no_es_exito_si_ambos_superan_presupuesto(self):
        b = balance_comparacion([fila(900), fila(850)], 800)
        self.assertEqual(b["categoria"], "Ninguno consiguió un viaje confirmado")
        self.assertIsNone(b["ahorro"])

    def test_mide_ahorro_solo_entre_dos_planes_viables(self):
        b = balance_comparacion([fila(750), fila(650)], 800)
        self.assertEqual(b["ahorro"], 100)
        self.assertIn("100.00", b["titulo"])

    def test_muestra_derrota_y_empate(self):
        self.assertEqual(balance_comparacion([fila(600), fila(650)], 800)["ahorro"], -50)
        self.assertEqual(balance_comparacion([fila(600), fila(600)], 800)["ahorro"], 0)
        self.assertEqual(balance_comparacion([fila(600), fila()], 800)["categoria"],
                         "Solo la lista consiguió un viaje")

    def test_tarifa_provisional_no_se_cuenta_como_viaje_conseguido(self):
        b = balance_comparacion([fila(), fila(400, False)], 800)
        self.assertFalse(b["metodos"][1]["viable"])
        self.assertIsNone(b["metodos"][1]["total"])

    def test_historial_sin_contador_no_se_presenta_como_cero_consultas(self):
        resultado = medir_resultado(("Antigua", [{}], [], []), 800)
        self.assertIsNone(resultado["consultas"])
        self.assertIsNone(resultado["llamadas_modelo"])
        self.assertIsNone(resultado["revisiones_invalidas"])
        self.assertEqual(resultado["hoteles_evitados"], 0)

    def test_cuenta_consultas_y_descartes_explicitos(self):
        resultado = medir_resultado(("Agente", [{"consultas_proveedor": 3,
            "diagnostico": {"consultas_hotel_evitadas": 1}, "revision_aplicada": True}], [], []), 800)
        self.assertEqual((resultado["consultas"], resultado["hoteles_evitados"], resultado["cambios"]), (3, 1, 1))
