"""Salida estructurada y verificable sin conectar Ollama."""

import json
import unittest

from src.agent import AgenteViajes
from src.tools import estimar_coste


class TestPresentacion(unittest.TestCase):
    def preparar(self, ids, presupuesto=1400, intereses="cultura", tipo="recomendacion"):
        agente = AgenteViajes(mostrar=lambda texto: None)
        texto = "Somos 2 personas, viajamos 4 días desde Madrid."
        if presupuesto is not None:
            texto += f" Tenemos {presupuesto} EUR en total."
        if intereses:
            texto += f" Nos gusta {intereses}."
        agente.historial.append({"role": "user", "content": texto})
        for destino in ids:
            agente.historial.append({
                "role": "tool", "tool_name": "estimar_coste",
                "content": json.dumps(estimar_coste(destino, "Madrid", 4, 2)),
            })
        propuesta = {
            "tipo": tipo, "destinos": ids, "origen": "Madrid",
            "duracion_dias": 4, "viajeros": 2, "presupuesto_total": presupuesto,
        }
        return agente, propuesta

    def redactar(self, ids, **opciones):
        agente, propuesta = self.preparar(ids, **opciones)
        respuesta, error = agente._redactar_propuesta(propuesta)
        self.assertIsNone(error)
        return respuesta

    def filas(self, texto):
        filas = [linea for linea in texto.splitlines() if linea.startswith("| ")]
        return [[celda.strip() for celda in fila.split("|")[1:-1]] for fila in filas[1:]]

    def test_datos_antes_de_tabla_y_explicaciones_despues(self):
        texto = self.redactar(["oporto"])
        self.assertLess(texto.index("Datos del viaje"), texto.index("| Destino"))
        self.assertLess(texto.index("| Destino"), texto.index("Por qué se proponen"))
        resumen = texto.split("| Destino")[0]
        for dato in ("Madrid", "4 días, 2 viajeros", "1400 EUR", "Intereses: cultura"):
            self.assertIn(dato, resumen)

    def test_tres_opciones_ordenadas_por_coste_no_por_orden_del_llm(self):
        filas = self.filas(self.redactar(["roma", "lisboa", "oporto"]))
        self.assertEqual([f[0] for f in filas], ["Oporto", "Lisboa", "Roma"])
        self.assertEqual([f[2] for f in filas], ["770 EUR", "910 EUR", "1180 EUR"])
        self.assertEqual([f[4] for f in filas], ["630 EUR", "490 EUR", "220 EUR"])

    def test_tabla_incluye_pais_precio_por_persona_y_caracteristicas(self):
        fila = self.filas(self.redactar(["oporto"]))[0]
        self.assertEqual(fila, [
            "Oporto", "Portugal", "770 EUR", "385 EUR", "630 EUR", "cultura, gastronomía",
        ])

    def test_una_opcion_no_se_completa_con_destinos_no_propuestos(self):
        texto = self.redactar(["oporto"])
        self.assertEqual(len(self.filas(texto)), 1)
        self.assertNotIn("Lisboa", texto)
        self.assertNotIn("Roma", texto)

    def test_margen_cero_y_presupuesto_con_decimales(self):
        self.assertEqual(self.filas(self.redactar(["roma"], presupuesto=1180))[0][4], "0 EUR")
        self.assertEqual(self.filas(self.redactar(["oporto"], presupuesto=800.5))[0][4], "30.5 EUR")

    def test_explicacion_relaciona_solo_intereses_coincidentes(self):
        texto = self.redactar(["oporto"], intereses="cultura y gastronomía")
        self.assertIn("Coincide con tus intereses en cultura, gastronomía.", texto)
        self.assertNotIn("playa", texto)
        self.assertNotIn("soleado", texto)
        self.assertNotIn("museos", texto)

    def test_sin_intereses_no_inventa_preferencias(self):
        texto = self.redactar(["oporto"], intereses="")
        self.assertIn("Intereses: No indicados", texto)
        self.assertIn("No indicaste intereses específicos.", texto)
        self.assertNotIn("Coincide con tus intereses", texto)

    def test_no_afirma_coincidencias_que_no_existen(self):
        texto = self.redactar(["oporto"], intereses="playa")
        self.assertIn("No hay coincidencia con los intereses indicados.", texto)
        self.assertNotIn("Coincide con tus intereses en playa", texto)

    def test_coste_sin_presupuesto_no_inventa_margen(self):
        texto = self.redactar(["lisboa"], presupuesto=None, intereses="", tipo="coste")
        self.assertIn("Presupuesto total: No indicado", texto)
        self.assertEqual(self.filas(texto)[0][4], "No disponible")
        self.assertNotIn("dentro del presupuesto", texto)

    def test_consulta_de_coste_muestra_margen_negativo_sin_recomendar(self):
        agente, propuesta = self.preparar(["lisboa"], presupuesto=800, tipo="coste")
        # El modelo puede omitir presupuesto; el resumen recupera el del usuario.
        propuesta["presupuesto_total"] = None
        texto, error = agente._redactar_propuesta(propuesta)
        self.assertIsNone(error)
        self.assertIn("Presupuesto total: 800 EUR", texto)
        self.assertEqual(self.filas(texto)[0][4], "-110 EUR")
        self.assertIn("Costes consultados", texto)
        self.assertNotIn("Destinos recomendados", texto)
        self.assertNotIn("dentro del presupuesto", texto)

    def test_tabla_no_implica_clasificacion_global(self):
        texto = self.redactar(["oporto"])
        self.assertIn("entre las opciones mostradas", texto)
        self.assertIn("no es una clasificación de todo el catálogo", texto)
        self.assertNotIn("el más barato", texto)

    def test_presupuesto_inventado_no_aparece_en_resumen_ni_margen(self):
        agente, propuesta = self.preparar(["lisboa"], presupuesto=800, tipo="coste")
        propuesta["presupuesto_total"] = 2000
        texto, error = agente._redactar_propuesta(propuesta)
        self.assertIsNone(texto)
        self.assertIn("presupuesto", error)

    def test_mantiene_limite_de_tres_y_estimaciones_obligatorias(self):
        agente, propuesta = self.preparar(["oporto", "lisboa", "roma", "atenas"])
        texto, error = agente._redactar_propuesta(propuesta)
        self.assertIsNone(texto)
        self.assertIsNotNone(error)
        agente, propuesta = self.preparar(["oporto"])
        propuesta["destinos"].append("praga")
        texto, error = agente._redactar_propuesta(propuesta)
        self.assertIsNone(texto)
        self.assertIn("Falta estimar_coste para praga", error)

    def test_bucle_ignora_texto_inventado_del_modelo_y_conserva_contexto(self):
        # El cliente simulado elige una herramienta y después una propuesta.
        class Cliente:
            def __init__(self):
                self.respuestas = iter([
                    {"role": "assistant", "content": "", "tool_calls": [{"function": {
                        "name": "estimar_coste", "arguments": {
                            "destino_id": "oporto", "origen": "Madrid", "duracion_dias": 4, "viajeros": 2,
                        },
                    }}]},
                    {"role": "assistant", "content": "Oporto cuesta 1 EUR y tiene playa.", "propuesta": {
                        "tipo": "recomendacion", "destinos": ["oporto"], "origen": "Madrid",
                        "duracion_dias": 4, "viajeros": 2, "presupuesto_total": 800,
                    }},
                ])

            def chat(self, mensajes):
                return next(self.respuestas)

        agente = AgenteViajes(Cliente(), mostrar=lambda texto: None)
        agente.historial.append({"role": "user", "content": "Nos gusta la cultura."})
        texto = agente.responder("Somos 2 personas, 4 días desde Madrid y 800 EUR en total.")
        self.assertIn("Intereses: cultura", texto)
        self.assertIn("770 EUR", texto)
        self.assertNotIn("1 EUR", texto)
        self.assertNotIn("playa", texto)
        self.assertEqual(self.filas(texto)[0][4], "30 EUR")


if __name__ == "__main__":
    unittest.main()
