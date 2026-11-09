import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.plan_colaborativo import AgentePreferenciasViaje, coordinar


class TestPlanColaborativo(unittest.TestCase):
    def test_descarta_una_ciudad_fuera_de_presupuesto(self):
        plan, trazas = coordinar("Valencia", 200, {})
        self.assertEqual((plan.ciudad, plan.total), ("Zaragoza", 158))
        self.assertTrue(any("220 € supera 200 €" in paso for paso in trazas))
        self.assertIsNone(coordinar("Valencia", 100, {})[0])

    def test_repara_transporte_conservando_el_hotel(self):
        inicial, _ = coordinar("Valencia", 250, {})
        reparado, _ = coordinar("Valencia", 250, {}, cancelado=inicial)
        self.assertNotEqual(reparado.transporte, inicial.transporte)
        self.assertEqual(reparado.alojamiento, inicial.alojamiento)
        self.assertEqual(reparado.total, 250)

    def test_repeticiones_cambian_el_plan_en_un_origen_nuevo(self):
        with TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "datos.sqlite3"
            memoria = AgentePreferenciasViaje(ruta)
            memoria.aprender("viaje-1", "cocina")
            memoria.aprender("viaje-1", "llegada_temprana")
            memoria.aprender("viaje-1", "llegada_temprana")
            empate, _ = coordinar("Sevilla", 185, memoria.perfil())
            self.assertTrue(empate.alojamiento.cocina)
            self.assertEqual(empate.transporte.llegada, 23)

            memoria.aprender("viaje-2", "llegada_temprana")
            perfil = AgentePreferenciasViaje(ruta).perfil()
            self.assertEqual(perfil["llegada_temprana"], 2)
            aprendido, _ = coordinar("Sevilla", 185, perfil)
            self.assertEqual((aprendido.transporte.llegada, aprendido.total), (18, 184))
            excepcion, _ = coordinar("Sevilla", 185, perfil, permitir_tarde=True)
            self.assertEqual(excepcion.transporte.llegada, 23)
            self.assertEqual(memoria.perfil(), perfil)
