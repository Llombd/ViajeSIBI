"""Pruebas locales con unittest, incluido en Python."""

import json
import unittest

from src.tools import CATALOGO, buscar_destinos, consultar_destino, estimar_coste


class TestHerramientas(unittest.TestCase):
    def test_catalogo_completo(self):
        with CATALOGO.open(encoding="utf-8") as archivo:
            catalogo = json.load(archivo)
        destinos = catalogo["destinos"]
        self.assertEqual(catalogo["tipo_datos"], "ficticios")
        self.assertEqual(len(destinos), 15)
        self.assertEqual(len({d["id"] for d in destinos}), 15)
        for destino in destinos:
            with self.subTest(destino=destino["id"]):
                self.assertEqual(destino["tipo_datos"], "ficticios")
                self.assertEqual(set(destino["clima_mensual"]), {str(m) for m in range(1, 13)})
                self.assertNotIn("error", estimar_coste(destino["id"], "Madrid", 4, 2))

    def test_busqueda_sin_filtros(self):
        self.assertEqual(len(buscar_destinos()["destinos"]), 15)

    def test_busqueda_combina_filtros_y_normaliza(self):
        resultado = buscar_destinos("SUR", ["cultura", "Gastronomía"])
        ids = {destino["id"] for destino in resultado["destinos"]}
        self.assertEqual(ids, {"lisboa", "oporto", "roma", "florencia"})

    def test_busqueda_sin_coincidencias(self):
        self.assertEqual(buscar_destinos(intereses=["esqui"])["destinos"], [])

    def test_argumentos_busqueda(self):
        self.assertIn("error", buscar_destinos(intereses="cultura"))
        self.assertIn("error", buscar_destinos(region=12))

    def test_consulta_mes(self):
        resultado = consultar_destino("lisboa", 5)
        self.assertEqual(resultado["nombre"], "Lisboa")
        self.assertEqual(resultado["clima"]["temperatura_media_c"], 18)
        self.assertEqual(resultado["tipo_datos"], "ficticios")

    def test_consulta_invalida(self):
        self.assertIn("error", consultar_destino("desconocido", 5))
        for mes in (0, 13, "mayo", True):
            with self.subTest(mes=mes):
                self.assertIn("error", consultar_destino("lisboa", mes))

    def test_desglose_coste(self):
        # Lisboa: 140*2 + 65*3*2 + 30*4*2 = 910 EUR.
        resultado = estimar_coste("lisboa", "madrid", 4, 2)
        self.assertEqual(resultado["desglose"], {
            "transporte": 280, "alojamiento": 390, "gastos_diarios": 240,
        })
        self.assertEqual(resultado["total_grupo"], 910)
        self.assertEqual(resultado["total_por_persona"], 455)

    def test_un_dia_no_incluye_noche(self):
        resultado = estimar_coste("lisboa", "Madrid", 1, 1)
        self.assertEqual(resultado["noches"], 0)
        self.assertEqual(resultado["total_grupo"], 170)

    def test_origen_y_destino_ausentes(self):
        self.assertIn("error", estimar_coste("lisboa", "Bilbao", 4, 2))
        self.assertIn("error", estimar_coste("desconocido", "Madrid", 4, 2))

    def test_duracion_y_viajeros_invalidos(self):
        for dias, viajeros in ((0, 2), (4, 0), (-1, 2), (4, 1.5), (True, 2)):
            with self.subTest(dias=dias, viajeros=viajeros):
                self.assertIn("error", estimar_coste("lisboa", "Madrid", dias, viajeros))


if __name__ == "__main__":
    unittest.main()
