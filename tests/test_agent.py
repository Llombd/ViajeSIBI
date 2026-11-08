"""Pruebas sin Ollama: simulamos sus decisiones, no las del agente."""

import copy
import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import URLError

from src.agent import AgenteViajes, ClienteOllama, ErrorOllama, ejecutar_herramienta


def llamada(nombre, argumentos):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": nombre, "arguments": argumentos}},
    ]}


def propuesta(ids, tipo="coste", presupuesto=None, dias=4, viajeros=2, origen="Madrid"):
    return {"role": "assistant", "content": "", "propuesta": {
        "tipo": tipo, "destinos": ids, "origen": origen,
        "duracion_dias": dias, "viajeros": viajeros, "presupuesto_total": presupuesto,
    }}


def coste(destino, dias=4, viajeros=2):
    return llamada("estimar_coste", {
        "destino_id": destino, "origen": "Madrid", "duracion_dias": dias, "viajeros": viajeros,
    })


class ClienteSimulado:
    def __init__(self, respuestas):
        self.respuestas = iter(respuestas)
        self.peticiones = []

    def chat(self, mensajes):
        self.peticiones.append(copy.deepcopy(mensajes))
        respuesta = next(self.respuestas)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


class TestAgente(unittest.TestCase):
    def test_consultas_sucesivas_y_resultados(self):
        cliente = ClienteSimulado([
            llamada("consultar_destino", {"destino_id": "lisboa", "mes": 5}),
            llamada("estimar_coste", {
                "destino_id": "lisboa", "origen": "Madrid", "duracion_dias": 4, "viajeros": 2,
            }),
            propuesta(["lisboa"]),
        ])
        trazas = []
        agente = AgenteViajes(cliente, mostrar=trazas.append)
        self.assertIn("910", agente.responder("Consulta Lisboa en mayo para dos viajeros, cuatro días."))
        resultado = cliente.peticiones[2][-1]
        self.assertEqual(resultado["role"], "tool")
        self.assertEqual(json.loads(resultado["content"])["total_grupo"], 910)
        self.assertEqual(len(trazas), 4)
        # No se obliga a buscar antes de consultar un destino conocido.
        self.assertEqual(cliente.peticiones[1][-1]["tool_name"], "consultar_destino")

    def test_respuesta_directa_e_historial(self):
        cliente = ClienteSimulado([
            {"role": "assistant", "content": "¿Cuál es tu presupuesto?"},
            {"role": "assistant", "content": "He anotado tu presupuesto."},
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        agente.responder("Somos dos y salimos de Madrid.")
        agente.responder("900 EUR en total.")
        self.assertEqual(cliente.peticiones[1][1]["content"], "Somos dos y salimos de Madrid.")
        self.assertEqual(cliente.peticiones[1][2]["content"], "¿Cuál es tu presupuesto?")

    def test_validacion_no_ejecuta_argumentos_invalidos(self):
        for nombre, argumentos in [
            ("desconocida", {}),
            ("consultar_destino", {"destino_id": "lisboa"}),
            ("buscar_destinos", {"extra": 1}),
            ("buscar_destinos", "no es objeto"),
            ("consultar_destino", {"destino_id": "lisboa", "mes": True}),
        ]:
            with self.subTest(nombre=nombre, argumentos=argumentos):
                self.assertIn("error", ejecutar_herramienta(nombre, argumentos))

    def test_error_de_herramienta_vuelve_al_modelo(self):
        cliente = ClienteSimulado([
            llamada("consultar_destino", {"destino_id": "lisboa"}),
            {"role": "assistant", "content": "¿En qué mes quieres viajar?"},
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        self.assertIn("mes", agente.responder("Consulta Lisboa"))
        self.assertIn("error", json.loads(cliente.peticiones[1][-1]["content"]))

    def test_importe_inventado_se_devuelve_al_modelo(self):
        cliente = ClienteSimulado([
            {"role": "assistant", "content": "Lisboa cuesta 850 EUR."},
            llamada("estimar_coste", {
                "destino_id": "lisboa", "origen": "Madrid", "duracion_dias": 4, "viajeros": 2,
            }),
            propuesta(["lisboa"]),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        self.assertIn("910", agente.responder("Lisboa desde Madrid para dos, cuatro días."))
        self.assertIn("estructurada", cliente.peticiones[1][-1]["content"])

    def test_caso_reportado_bloquea_bruselas_y_busca_alternativa(self):
        cliente = ClienteSimulado([
            llamada("buscar_destinos", {"region": "oeste", "intereses": ["cultura"]}),
            coste("paris"), coste("amsterdam"),
            {"role": "assistant", "content": "Recomiendo Bruselas, cuesta 800 €."},
            propuesta(["bruselas"], "recomendacion", 800),
            coste("bruselas"),
            propuesta(["bruselas"], "recomendacion", 800),
            coste("oporto"),
            propuesta(["oporto"], "recomendacion", 800),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        respuesta = agente.responder(
            "Quiero viajar 4 días desde Madrid con otra persona. Tenemos 800 € "
            "en total y nos gustan las ciudades culturales. ¿Qué destinos recomiendas?"
        )
        self.assertIn("Oporto", respuesta)
        self.assertIn("770 EUR", respuesta)
        self.assertNotIn("Bruselas", respuesta)
        self.assertNotIn("800 €", respuesta)
        resultados = [m for m in agente.historial if m["role"] == "tool"]
        encontrados = json.loads(resultados[0]["content"])["destinos"]
        self.assertEqual(len(encontrados), 15)
        # La salida inválida no queda como respuesta aceptada en el historial.
        self.assertFalse(any("cuesta 800" in m["content"] for m in agente.historial))

    def test_precio_de_otro_destino_no_respalda_bruselas(self):
        cliente = ClienteSimulado([
            coste("paris"),
            {"role": "assistant", "content": "Bruselas cuesta 1440 EUR."},
            propuesta(["bruselas"]),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=3)
        respuesta = agente.responder("Consulta precios desde Madrid para dos y cuatro días.")
        self.assertIn("límite", respuesta)
        self.assertNotIn("Bruselas", respuesta)
        self.assertNotIn("1440", respuesta)

    def test_no_afirma_compatibilidad_sin_estimar(self):
        cliente = ClienteSimulado([
            {"role": "assistant", "content": "Bruselas cumple tu presupuesto."},
            propuesta(["bruselas"], "recomendacion", 800),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=2)
        respuesta = agente.responder("Tengo 800 EUR en total, cuatro días desde Madrid, dos personas.")
        self.assertIn("límite", respuesta)
        self.assertNotIn("Bruselas", respuesta)

    def test_no_acepta_estimacion_de_otros_parametros(self):
        for cambios in ({"dias": 3}, {"viajeros": 1}, {"origen": "Bilbao"}):
            with self.subTest(cambios=cambios):
                cliente = ClienteSimulado([coste("oporto"), propuesta(["oporto"], **cambios)])
                agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=2)
                self.assertIn("límite", agente.responder("Consulta Oporto"))

    def test_destino_fuera_de_presupuesto_se_rechaza(self):
        cliente = ClienteSimulado([
            coste("bruselas"), propuesta(["bruselas"], "recomendacion", 800),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=2)
        respuesta = agente.responder("Presupuesto de 800 EUR en total.")
        self.assertIn("límite", respuesta)
        self.assertNotIn("Dentro del presupuesto", respuesta)

    def test_presupuesto_inventado_o_anterior_no_se_acepta(self):
        cliente = ClienteSimulado([
            coste("oporto"), propuesta(["oporto"], "recomendacion", 1000),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=2)
        self.assertIn("límite", agente.responder("Ahora solo tenemos 700 EUR en total."))

    def test_propuesta_usa_precio_de_herramienta_ignora_texto_llm(self):
        final = propuesta(["oporto"], "recomendacion", 800)
        final["content"] = "Oporto cuesta 800 EUR y Bruselas es gratis."
        cliente = ClienteSimulado([coste("oporto"), final])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        respuesta = agente.responder("800 EUR de presupuesto total.")
        self.assertIn("770 EUR", respuesta)
        self.assertNotIn("gratis", respuesta)
        self.assertNotIn("Bruselas", respuesta)

    def test_region_explicita_se_conserva(self):
        cliente = ClienteSimulado([
            llamada("buscar_destinos", {"region": "sur", "intereses": ["cultura"]}),
            {"role": "assistant", "content": "¿Cuál es tu presupuesto?"},
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        agente.responder("Quiero ciudades culturales del sur de Europa.")
        encontrados = json.loads(cliente.peticiones[1][-1]["content"])["destinos"]
        self.assertTrue(all(d["region"] == "sur" for d in encontrados))
        self.assertEqual(len(encontrados), 6)

    def test_region_se_conserva_en_sesion_y_se_puede_quitar(self):
        cliente = ClienteSimulado([
            {"role": "assistant", "content": "¿Desde dónde quieres salir?"},
            llamada("buscar_destinos", {"region": "sur"}),
            {"role": "assistant", "content": "¿Cuál es tu presupuesto?"},
            llamada("buscar_destinos", {"region": "sur"}),
            {"role": "assistant", "content": "¿Cuántos días quieres viajar?"},
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        agente.responder("Quiero viajar al sur de Europa.")
        agente.responder("Cultura")
        self.assertEqual(agente._regiones_usuario(), {"sur"})
        agente.responder("Ahora cualquier región de toda Europa.")
        encontrados = json.loads(cliente.peticiones[-1][-1]["content"])["destinos"]
        self.assertEqual(len(encontrados), 15)

    def test_correcciones_internas_no_autorizan_region_ni_presupuesto(self):
        agente = AgenteViajes(ClienteSimulado([]), mostrar=lambda texto: None)
        agente.historial.extend([
            {"role": "user", "content": "Tenemos 800 EUR en total."},
            {"role": "user", "interno": True, "content": "Error: región oeste; 1200 EUR."},
        ])
        self.assertEqual(agente._regiones_usuario(), set())
        _, error = agente._redactar_propuesta(
            propuesta(["oporto"], "recomendacion", 1200)["propuesta"]
        )
        self.assertIn("presupuesto", error)

    def test_estimar_error_no_crea_precio_valido(self):
        cliente = ClienteSimulado([
            llamada("estimar_coste", {
                "destino_id": "oporto", "origen": "Bilbao", "duracion_dias": 4, "viajeros": 2,
            }),
            propuesta(["oporto"], origen="Bilbao"),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=2)
        self.assertIn("límite", agente.responder("Consulta Oporto desde Bilbao."))

    def test_viaje_barato_dos_turnos_sin_intereses_inventados(self):
        cliente = ClienteSimulado([
            {"role": "assistant", "content": "¿Cuántos días, viajeros y qué región prefieres?"},
            {"role": "assistant", "content": "¿Desde dónde salís, cuántos sois, cuántos días y qué presupuesto total tenéis?"},
            llamada("buscar_destinos", {
                "region": "oeste", "intereses": ["cultura", "gastronomia", "playa", "naturaleza"],
            }),
            coste("oporto"),
            propuesta(["oporto"], "recomendacion", 800),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        pregunta = agente.responder("Quiero hacer un viaje barato por Europa.")
        self.assertIn("presupuesto", pregunta)
        self.assertNotIn("región", pregunta)
        respuesta = agente.responder(
            "Somos 2 personas, queremos viajar 4 días, salimos desde Madrid y tenemos "
            "un presupuesto máximo de 800 € en total. Nos da igual la región."
        )
        self.assertIn("770 EUR", respuesta)
        self.assertIn("4 días, 2 viajeros", respuesta)
        self.assertIn("Madrid", respuesta)
        self.assertEqual(agente._faltan_datos_imprescindibles(), [])
        # Se ejecutó y registró la llamada corregida, sin región ni intereses.
        llamadas = [c["function"] for m in agente.historial for c in m.get("tool_calls", [])]
        self.assertEqual(llamadas[0]["arguments"], {})
        resultado = json.loads(cliente.peticiones[3][-1]["content"])
        self.assertEqual(len(resultado["destinos"]), 15)
        self.assertTrue(any("salimos desde Madrid" in m["content"]
                            for m in cliente.peticiones[-1] if m["role"] == "user"))

    def test_solo_conserva_intereses_explicitos(self):
        cliente = ClienteSimulado([
            llamada("buscar_destinos", {"intereses": ["cultura", "playa"]}),
            {"role": "assistant", "content": "¿Desde dónde quieres salir?"},
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        agente.responder("Nos gustan las ciudades culturales.")
        funcion = agente.historial[2]["tool_calls"][0]["function"]
        self.assertEqual(funcion["arguments"], {"intereses": ["cultura"]})
        self.assertEqual(len(json.loads(cliente.peticiones[1][-1]["content"])["destinos"]), 15)

    def test_exclusion_no_se_convierte_en_interes(self):
        cliente = ClienteSimulado([
            llamada("buscar_destinos", {"intereses": ["cultura", "playa"]}),
            {"role": "assistant", "content": "¿Cuántos días quieres viajar?"},
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        agente.responder("Nos gusta la cultura, pero no queremos playa.")
        self.assertEqual(agente.historial[2]["tool_calls"][0]["function"]["arguments"],
                         {"intereses": ["cultura"]})

    def test_intereses_persisten_sin_inventar_nuevos(self):
        cliente = ClienteSimulado([
            {"role": "assistant", "content": "¿Desde dónde salís?"},
            llamada("buscar_destinos", {"intereses": ["gastronomia", "naturaleza"]}),
            {"role": "assistant", "content": "¿Qué presupuesto tenéis?"},
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        agente.responder("Nos gusta la gastronomía.")
        agente.responder("Somos 2 personas y salimos desde Madrid por 4 días.")
        funcion = agente.historial[4]["tool_calls"][0]["function"]
        self.assertEqual(funcion["arguments"], {"intereses": ["gastronomia"]})

    def test_indiferencia_regional_elimina_preferencia_anterior(self):
        for frase in ("Nos da igual la región", "La región me da igual", "Me da igual la región"):
            with self.subTest(frase=frase):
                cliente = ClienteSimulado([
                    {"role": "assistant", "content": "¿Cuántos días viajarás?"},
                    llamada("buscar_destinos", {"region": "sur"}),
                    {"role": "assistant", "content": "¿Desde dónde sales?"},
                ])
                agente = AgenteViajes(cliente, mostrar=lambda texto: None)
                agente.responder("Me gustaría el sur de Europa.")
                agente.responder(frase)
                self.assertEqual(agente._regiones_usuario(), set())
                self.assertEqual(len(json.loads(cliente.peticiones[-1][-1]["content"])["destinos"]), 15)

    def test_mensajes_del_agente_no_crean_intereses(self):
        agente = AgenteViajes(ClienteSimulado([]), mostrar=lambda texto: None)
        agente.historial.extend([
            {"role": "assistant", "content": "cultura, gastronomia, playa, naturaleza"},
            {"role": "user", "interno": True, "content": "Intereses: cultura y playa"},
            {"role": "user", "content": "Quiero un viaje barato."},
        ])
        self.assertEqual(agente._intereses_usuario(), set())
        self.assertEqual(agente._ajustar_filtros_busqueda({"intereses": ["cultura", "playa"]}), {})

    def test_busqueda_vacia_revisa_filtros_sin_descartar_gustos(self):
        cliente = ClienteSimulado([
            llamada("buscar_destinos", {
                "intereses": ["cultura", "gastronomia", "playa", "naturaleza"],
            }),
            {"role": "assistant", "content": "No hay destinos disponibles."},
            {"role": "assistant", "content": "No hay coincidencias con estos filtros. ¿Queréis flexibilizar los intereses?"},
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        respuesta = agente.responder(
            "Queremos cultura, gastronomía, playa y naturaleza. Somos 2 personas, "
            "4 días desde Madrid, 800 EUR en total."
        )
        self.assertIn("sin coincidencias", cliente.peticiones[1][-1]["content"].lower())
        self.assertIn("Revisa si son necesarios", cliente.peticiones[2][-1]["content"])
        self.assertIn("flexibilizar", respuesta)
        self.assertNotIn("No hay destinos disponibles", respuesta)
        llamadas = [c for m in agente.historial for c in m.get("tool_calls", [])]
        self.assertEqual(len(llamadas), 1)  # No se borran gustos explícitos ni se fuerza otra consulta.

    def test_no_concluye_ausencia_sin_consultar_catalogo(self):
        cliente = ClienteSimulado([
            {"role": "assistant", "content": "No hay destinos disponibles."},
            llamada("buscar_destinos", {}),
            {"role": "assistant", "content": "¿Cuál es tu presupuesto?"},
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        respuesta = agente.responder("Quiero un viaje barato por Europa.")
        self.assertNotIn("No hay destinos", respuesta)
        self.assertEqual(len(json.loads(cliente.peticiones[-1][-1]["content"])["destinos"]), 15)

    def test_quitar_intereses_tras_busqueda_vacia_permite_buscar_todos(self):
        cliente = ClienteSimulado([
            llamada("buscar_destinos", {"intereses": ["cultura", "playa", "naturaleza"]}),
            {"role": "assistant", "content": "No hay coincidencias con estos filtros. ¿Queréis flexibilizarlos?"},
            llamada("buscar_destinos", {"intereses": ["cultura", "playa", "naturaleza"]}),
            coste("oporto"),
            propuesta(["oporto"], "recomendacion", 800),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        agente.responder("Nos gustan cultura, playa y naturaleza. Somos 2 personas, 4 días desde Madrid, 800 EUR.")
        respuesta = agente.responder("Ahora sin intereses concretos, y nos da igual la región.")
        self.assertIn("770 EUR", respuesta)
        busquedas = [c["function"] for m in agente.historial for c in m.get("tool_calls", [])
                     if c["function"]["name"] == "buscar_destinos"]
        self.assertEqual(busquedas[-1]["arguments"], {})

    def test_limite_consultas(self):
        cliente = ClienteSimulado([llamada("buscar_destinos", {})] * 2)
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=2)
        self.assertIn("límite", agente.responder("Busca destinos"))
        self.assertEqual(len(cliente.peticiones), 2)

    def test_limite_herramientas_en_un_lote(self):
        respuesta = llamada("buscar_destinos", {})
        respuesta["tool_calls"] *= 3
        cliente = ClienteSimulado([respuesta])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_herramientas=1)
        with patch("src.agent.ejecutar_herramienta", return_value={"destinos": []}) as ejecutar:
            self.assertIn("límite", agente.responder("Busca"))
            self.assertEqual(ejecutar.call_count, 1)
        resultados = [m for m in agente.historial if m["role"] == "tool"]
        self.assertEqual(len(resultados), 3)
        self.assertIn("error", json.loads(resultados[-1]["content"]))

    def test_fallo_conexion_conserva_sesion_anterior(self):
        cliente = ClienteSimulado([
            {"role": "assistant", "content": "Hola"},
            llamada("buscar_destinos", {}),
            ErrorOllama("Sin conexión"),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        agente.responder("Hola")
        anterior = copy.deepcopy(agente.historial)
        with self.assertRaises(ErrorOllama):
            agente.responder("Busca destinos")
        self.assertEqual(agente.historial, anterior)

    def test_cliente_envia_configuracion_y_no_guarda_thinking(self):
        respuesta = MagicMock()
        respuesta.__enter__.return_value.read.return_value = json.dumps({
            "message": {"role": "assistant", "content": json.dumps({
                "herramienta": "ninguna", "argumentos": {}, "respuesta": "Hola",
            }), "thinking": "No mostrar"},
        }).encode()
        with patch("src.agent.urlopen", return_value=respuesta) as abrir:
            mensaje = ClienteOllama().chat([{"role": "user", "content": "Hola"}])
        datos = json.loads(abrir.call_args.args[0].data)
        self.assertEqual(datos["model"], "qwen3:4b")
        self.assertFalse(datos["think"])
        self.assertFalse(datos["stream"])
        self.assertEqual(len(datos["format"]["properties"]["herramienta"]["enum"]), 4)
        self.assertIn("estimar_coste", datos["messages"][0]["content"])
        self.assertNotIn("thinking", mensaje)

    def test_cliente_conserva_propuesta_estructurada(self):
        final = propuesta(["oporto"], "recomendacion", 800)
        respuesta = MagicMock()
        respuesta.__enter__.return_value.read.return_value = json.dumps({
            "message": {"role": "assistant", "content": json.dumps({
                "herramienta": "ninguna", "argumentos": final["propuesta"], "respuesta": "",
            })},
        }).encode()
        with patch("src.agent.urlopen", return_value=respuesta) as abrir:
            recibido = ClienteOllama().chat([
                {"role": "system", "content": "Instrucciones"},
                final,
                {"role": "user", "content": "Gracias"},
            ])
        self.assertEqual(recibido["propuesta"], final["propuesta"])
        datos = json.loads(abrir.call_args.args[0].data)
        anterior = json.loads(datos["messages"][1]["content"])
        self.assertEqual(anterior["argumentos"], final["propuesta"])

    def test_cliente_rechaza_salida_truncada(self):
        respuesta = MagicMock()
        respuesta.__enter__.return_value.read.return_value = json.dumps({
            "done_reason": "length",
            "message": {"role": "assistant", "content": "Respuesta incompleta"},
        }).encode()
        with patch("src.agent.urlopen", return_value=respuesta):
            with self.assertRaises(ErrorOllama):
                ClienteOllama().chat([])

    def test_cliente_error_conexion(self):
        with patch("src.agent.urlopen", side_effect=URLError("Sin conexión")):
            with self.assertRaises(ErrorOllama):
                ClienteOllama().chat([])

    def test_cliente_rechaza_llamada_mal_formada(self):
        respuesta = MagicMock()
        respuesta.__enter__.return_value.read.return_value = json.dumps({
            "message": {"role": "assistant", "tool_calls": [{"function": None}]},
        }).encode()
        with patch("src.agent.urlopen", return_value=respuesta):
            with self.assertRaises(ErrorOllama):
                ClienteOllama().chat([])


class TestVariasRecomendaciones(unittest.TestCase):
    peticion = ("Somos 2 personas, 4 días desde Madrid, 1400 EUR en total. "
                "Nos gusta la cultura. Recomienda hasta tres destinos.")

    def filas(self, texto):
        filas = [linea for linea in texto.splitlines() if linea.startswith("| ")]
        return [[celda.strip() for celda in fila.split("|")[1:-1]] for fila in filas[1:]]

    def test_no_cierra_con_una_si_quedan_alternativas(self):
        cliente = ClienteSimulado([
            coste("oporto"), propuesta(["oporto"], "recomendacion", 1400),
            coste("roma"), coste("lisboa"), propuesta(["roma"], "recomendacion", 1400),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        texto = agente.responder(self.peticion)
        self.assertEqual([f[0] for f in self.filas(texto)], ["Oporto", "Lisboa", "Roma"])
        self.assertEqual([f[2] for f in self.filas(texto)], ["770 EUR", "910 EUR", "1180 EUR"])
        self.assertIn("solo hay 1 con coste verificado", cliente.peticiones[2][-1]["content"])
        llamadas = [c["function"]["arguments"]["destino_id"]
                    for m in agente.historial for c in m.get("tool_calls", [])]
        self.assertEqual(llamadas, ["oporto", "roma", "lisboa"])
        self.assertIn("Datos del viaje", texto)
        self.assertIn("Por qué se proponen", texto)

    def test_reutiliza_costes_de_la_sesion_sin_repetirlos(self):
        cliente = ClienteSimulado([
            coste("oporto"), propuesta(["oporto"], "recomendacion", 1400),
            propuesta(["oporto"], "recomendacion", 1400),
            coste("praga"), coste("budapest"), propuesta(["praga"], "recomendacion", 1400),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        agente.responder(self.peticion.replace("hasta tres destinos", "un destino"))
        texto = agente.responder("Ahora quiero tres destinos, manteniendo los datos.")
        self.assertEqual([f[0] for f in self.filas(texto)], ["Oporto", "Budapest", "Praga"])
        costes = [m for m in agente.historial if m["role"] == "tool" and m["tool_name"] == "estimar_coste"]
        self.assertEqual(len(costes), 3)

    def test_solo_dos_destinos_compatibles_no_inventa_un_tercero(self):
        cliente = ClienteSimulado([
            coste("atenas"), coste("barcelona"), propuesta(["barcelona"], "recomendacion", 2000),
        ])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None).responder(
            "Somos 2 personas, 4 días desde Madrid, 2000 EUR. Queremos playa y tres destinos."
        )
        self.assertEqual([f[0] for f in self.filas(texto)], ["Barcelona", "Atenas"])
        self.assertIn("Solo hay 2 opciones válidas", texto)
        self.assertIn("todos los destinos compatibles", texto)
        self.assertNotIn("se alcanzó el límite", texto)

    def test_solo_una_valida_tras_comprobar_todos_los_candidatos(self):
        cliente = ClienteSimulado([
            coste("paris"), coste("amsterdam"), coste("bruselas"),
            propuesta(["bruselas"], "recomendacion", 1100),
        ])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None).responder(
            "Somos 2 personas, 4 días desde Madrid, 1100 EUR. Queremos cultura en la región oeste y tres opciones."
        )
        self.assertEqual([f[0] for f in self.filas(texto)], ["Bruselas"])
        self.assertEqual(self.filas(texto)[0][2], "1056 EUR")
        self.assertIn("Solo hay 1 opción válida", texto)
        self.assertNotIn("se alcanzó el límite", texto)

    def test_descarta_caro_y_no_usa_tres_como_excusa_para_incluirlo(self):
        cliente = ClienteSimulado([
            coste("paris"), coste("oporto"), coste("budapest"), coste("praga"),
            propuesta(["oporto"], "recomendacion", 1400),
        ])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None).responder(self.peticion)
        self.assertEqual(len(self.filas(texto)), 3)
        self.assertNotIn("París", texto)
        self.assertNotIn("1440 EUR", texto)

    def test_limite_consultas_muestra_las_verificadas_sin_afirmar_exhaustividad(self):
        cliente = ClienteSimulado([coste("oporto"), coste("lisboa")])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=2)
        texto = agente.responder(self.peticion)
        self.assertEqual(len(cliente.peticiones), 2)
        self.assertEqual([f[0] for f in self.filas(texto)], ["Oporto", "Lisboa"])
        self.assertIn("se alcanzó el límite", texto)
        self.assertIn("Quedan candidatos sin comprobar", texto)
        self.assertNotIn("Solo hay", texto)

    def test_limite_herramientas_no_se_supera_para_completar_tres(self):
        cliente = ClienteSimulado([coste("oporto"), coste("lisboa")])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_herramientas=1)
        with patch("src.agent.ejecutar_herramienta", wraps=ejecutar_herramienta) as ejecutar:
            texto = agente.responder(self.peticion)
        self.assertEqual(ejecutar.call_count, 1)
        self.assertEqual([f[0] for f in self.filas(texto)], ["Oporto"])
        self.assertNotIn("Lisboa", texto)
        self.assertIn("Quedan candidatos sin comprobar", texto)

    def test_costes_de_otro_viaje_no_completan_la_tabla(self):
        cliente = ClienteSimulado([coste("oporto")])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=1)
        from src.tools import estimar_coste
        for destino, dias, viajeros in [("roma", 3, 2), ("lisboa", 4, 1)]:
            agente.historial.append({
                "role": "tool", "tool_name": "estimar_coste",
                "content": json.dumps(estimar_coste(destino, "Madrid", dias, viajeros)),
            })
        texto = agente.responder(self.peticion)
        self.assertEqual([f[0] for f in self.filas(texto)], ["Oporto"])

    def test_coste_fallido_no_cuenta_como_alternativa(self):
        cliente = ClienteSimulado([
            llamada("estimar_coste", {
                "destino_id": "lisboa", "origen": "Bilbao", "duracion_dias": 4, "viajeros": 2,
            }),
            coste("oporto"),
        ])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=2).responder(self.peticion)
        self.assertEqual([f[0] for f in self.filas(texto)], ["Oporto"])
        self.assertIn("Quedan candidatos sin comprobar", texto)

    def test_no_rellena_con_destinos_ajenos_a_los_filtros(self):
        cliente = ClienteSimulado([
            coste("oporto"), coste("copenhague"), coste("estocolmo"),
            propuesta(["copenhague"], "recomendacion", 2000),
        ])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None).responder(
            "Somos 2 personas, 4 días desde Madrid, 2000 EUR. Queremos cultura y naturaleza "
            "en el norte de Europa y tres destinos."
        )
        self.assertEqual([f[0] for f in self.filas(texto)], ["Estocolmo", "Copenhague"])
        self.assertNotIn("Oporto", texto)

    def test_dos_solicitadas_no_se_convierten_en_tres(self):
        cliente = ClienteSimulado([
            coste("roma"), coste("oporto"), coste("lisboa"),
            propuesta(["roma"], "recomendacion", 1400),
        ])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None).responder(
            self.peticion.replace("hasta tres destinos", "dos alternativas")
        )
        self.assertEqual([f[0] for f in self.filas(texto)], ["Oporto", "Lisboa"])

    def test_cantidad_no_confunde_viajeros_y_dias_con_destinos(self):
        for texto, esperado in [
            ("Somos 3 personas y viajamos 2 días", 1),
            ("Quiero un destino", 1), ("Hasta tres recomendaciones", 3),
            ("Dame varias alternativas", 3), ("Quiero dos destinos", 2),
            ("Quiero 5 destinos", 3),
        ]:
            with self.subTest(texto=texto):
                agente = AgenteViajes(ClienteSimulado([]), mostrar=lambda texto: None)
                agente.historial.append({"role": "user", "content": texto})
                self.assertEqual(agente._cantidad_solicitada(), esperado)

    def test_repetir_un_coste_no_cuenta_como_tres_destinos(self):
        cliente = ClienteSimulado([coste("oporto"), coste("oporto"), coste("oporto")])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=3).responder(self.peticion)
        self.assertEqual([f[0] for f in self.filas(texto)], ["Oporto"])
        self.assertIn("Quedan candidatos sin comprobar", texto)

    def test_una_solicitada_y_consulta_de_precio_conservan_comportamiento(self):
        cliente = ClienteSimulado([
            coste("oporto"), propuesta(["oporto"], "recomendacion", 1400),
            propuesta(["oporto"], "coste"),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        texto = agente.responder(self.peticion.replace("hasta tres destinos", "un destino"))
        self.assertEqual(len(self.filas(texto)), 1)
        # Una pregunta de coste posterior a una petición múltiple no fuerza alternativas.
        agente.historial.append({"role": "user", "content": "Dame tres destinos"})
        texto = agente.responder("¿Cuánto cuesta Oporto con esos datos?")
        self.assertIn("Costes consultados", texto)
        self.assertEqual(len(self.filas(texto)), 1)


class TestCierrePorLimite(unittest.TestCase):
    peticion = ("Somos 2 personas, cuatro días desde Madrid, 500 EUR en total. "
                "Nos gusta la cultura. Recomienda hasta tres destinos.")

    def filas(self, texto):
        filas = [linea for linea in texto.splitlines() if linea.startswith("| ")]
        return [[celda.strip() for celda in fila.split("|")[1:-1]] for fila in filas[1:]]

    def test_caso_real_500_con_propuestas_bloqueadas_cierra_con_datos(self):
        cliente = ClienteSimulado([
            coste("lisboa"), coste("oporto"), coste("barcelona"),
            propuesta(["lisboa"], "recomendacion", 500),
            propuesta(["oporto"], "recomendacion", 500),
        ])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=5).responder(self.peticion)
        self.assertEqual([f[0] for f in self.filas(texto)], ["Oporto", "Lisboa", "Barcelona"])
        self.assertEqual([f[2] for f in self.filas(texto)], ["770 EUR", "910 EUR", "990 EUR"])
        self.assertIn("no recomendados", texto)
        self.assertIn("Los destinos comprobados superan el presupuesto", texto)
        self.assertIn("Quedan 12 candidatos compatibles sin verificar", texto)
        self.assertIn("Datos del viaje", texto)
        self.assertIn("500 EUR", texto)
        self.assertNotIn("Destinos recomendados con coste comprobado", texto)
        self.assertNotIn("todos los candidatos compatibles con tus preferencias", texto)

    def test_cierre_util_tambien_si_se_pedia_un_solo_destino(self):
        cliente = ClienteSimulado([coste("lisboa")])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=1).responder(
            self.peticion.replace("hasta tres destinos", "un destino")
        )
        self.assertIn("910 EUR", texto)
        self.assertIn("no se recomiendan", texto)
        self.assertIn("sin verificar", texto)

    def test_todos_los_candidatos_comprobados_permite_conclusion_acotada(self):
        cliente = ClienteSimulado([coste("paris"), coste("amsterdam"), coste("bruselas")])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=3).responder(
            self.peticion + " Solo la región oeste."
        )
        self.assertEqual(len(self.filas(texto)), 3)
        self.assertIn("todos los candidatos compatibles con tus preferencias", texto)
        self.assertIn("ninguno cumple el presupuesto indicado", texto)
        self.assertNotIn("candidatos compatibles sin verificar", texto)

    def test_limite_herramientas_tambien_muestra_descartados_verificados(self):
        cliente = ClienteSimulado([coste("lisboa"), coste("oporto")])
        with patch("src.agent.ejecutar_herramienta", wraps=ejecutar_herramienta) as ejecutar:
            texto = AgenteViajes(cliente, mostrar=lambda texto: None, max_herramientas=1).responder(self.peticion)
        self.assertEqual(ejecutar.call_count, 1)
        self.assertEqual([f[0] for f in self.filas(texto)], ["Lisboa"])
        self.assertNotIn("770 EUR", texto)
        self.assertIn("sin verificar", texto)

    def test_una_valida_no_se_pierde_entre_opciones_caras(self):
        cliente = ClienteSimulado([
            coste("lisboa"), coste("oporto"), propuesta(["lisboa"], "recomendacion", 800),
        ])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=3).responder(
            self.peticion.replace("500 EUR", "800 EUR")
        )
        self.assertEqual([f[0] for f in self.filas(texto)], ["Oporto"])
        self.assertIn("Destinos recomendados con coste comprobado", texto)
        self.assertIn("Quedan candidatos sin comprobar", texto)
        self.assertNotIn("910 EUR", texto)

    def test_dos_validas_se_muestran_tras_propuesta_sin_estimar(self):
        cliente = ClienteSimulado([
            coste("oporto"), coste("lisboa"), propuesta(["roma"], "recomendacion", 1400),
        ])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=3).responder(
            self.peticion.replace("500 EUR", "1400 EUR")
        )
        self.assertEqual([f[0] for f in self.filas(texto)], ["Oporto", "Lisboa"])
        self.assertNotIn("Roma", texto)
        self.assertIn("Quedan candidatos sin comprobar", texto)

    def test_costes_fallidos_no_justifican_afirmar_ausencia(self):
        cliente = ClienteSimulado([llamada("estimar_coste", {
            "destino_id": "lisboa", "origen": "Bilbao", "duracion_dias": 4, "viajeros": 2,
        })])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=1).responder(self.peticion)
        self.assertIn("límite", texto)
        self.assertEqual(self.filas(texto), [])
        self.assertNotIn("ninguno cumple", texto)
        self.assertNotIn("superan el presupuesto", texto)

    def test_cierre_no_mezcla_otros_viajes(self):
        from src.tools import estimar_coste
        cliente = ClienteSimulado([coste("lisboa")])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=1)
        agente.historial.append({
            "role": "tool", "tool_name": "estimar_coste",
            "content": json.dumps(estimar_coste("oporto", "Madrid", 1, 1)),
        })
        texto = agente.responder(self.peticion)
        self.assertEqual([f[0] for f in self.filas(texto)], ["Lisboa"])
        self.assertIn("Quedan 14 candidatos compatibles sin verificar", texto)

    def test_cierre_solo_cuenta_candidatos_compatibles_con_filtros(self):
        cliente = ClienteSimulado([coste("oporto"), coste("barcelona")])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=2).responder(
            self.peticion.replace("cultura", "playa")
        )
        self.assertEqual([f[0] for f in self.filas(texto)], ["Barcelona"])
        self.assertIn("Queda", texto)
        self.assertIn("1 candidato compatible sin verificar", texto)

    def test_repetir_descartado_no_recalcula_y_no_se_acepta_como_recomendacion(self):
        cliente = ClienteSimulado([
            coste("lisboa"), coste("lisboa"), propuesta(["lisboa"], "recomendacion", 500),
        ])
        with patch("src.agent.ejecutar_herramienta", wraps=ejecutar_herramienta) as ejecutar:
            texto = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=3).responder(self.peticion)
        self.assertEqual(ejecutar.call_count, 1)
        self.assertIn("Descartado por presupuesto", cliente.peticiones[1][-1]["content"])
        self.assertIn("No vuelvas a proponerlo", cliente.peticiones[1][-1]["content"])
        self.assertEqual(len(self.filas(texto)), 1)
        self.assertIn("no recomendados", texto)

    def test_subir_presupuesto_permite_reconsiderar_destino(self):
        cliente = ClienteSimulado([
            coste("lisboa"), coste("lisboa"), propuesta(["lisboa"], "recomendacion", 1000),
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=1)
        with patch("src.agent.ejecutar_herramienta", wraps=ejecutar_herramienta) as ejecutar:
            agente.responder(self.peticion.replace("hasta tres destinos", "un destino"))
            agente.max_consultas = 2
            texto = agente.responder("Ahora tenemos 1000 EUR en total. Recomienda un destino.")
        self.assertEqual(ejecutar.call_count, 2)
        self.assertIn("Destinos recomendados con coste comprobado", texto)
        self.assertIn("910 EUR", texto)
        self.assertNotIn("fuera de presupuesto", texto)

    def test_cambiar_duracion_no_reutiliza_un_descarte_anterior(self):
        cliente = ClienteSimulado([coste("lisboa"), coste("lisboa", dias=1)])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=1)
        with patch("src.agent.ejecutar_herramienta", wraps=ejecutar_herramienta) as ejecutar:
            agente.responder(self.peticion)
            texto = agente.responder("Ahora viajaremos 1 día con el mismo presupuesto y viajeros.")
        self.assertEqual(ejecutar.call_count, 2)
        self.assertIn("340 EUR", texto)
        self.assertNotIn("910 EUR", texto)

    def test_presupuesto_inventado_del_modelo_no_contamina_el_cierre(self):
        cliente = ClienteSimulado([
            coste("lisboa"), propuesta(["lisboa"], "recomendacion", 9999),
        ])
        texto = AgenteViajes(cliente, mostrar=lambda texto: None, max_consultas=2).responder(self.peticion)
        self.assertIn("Presupuesto total: 500 EUR", texto)
        self.assertIn("910 EUR", texto)
        self.assertNotIn("9999", texto)
        self.assertIn("no se recomiendan", texto)


class TestActualizacionPresupuesto(unittest.TestCase):
    def crear(self, respuestas=()):
        cliente = ClienteSimulado(respuestas)
        return AgenteViajes(cliente, mostrar=lambda texto: None), cliente

    def test_sin_moneda_pregunta_sin_consultar_modelo(self):
        agente, cliente = self.crear()
        texto = agente.responder("Somos dos personas, cuatro días desde Madrid, cultura y tenemos 1400. Recomienda tres destinos.")
        self.assertIn("1400 EUR", texto)
        self.assertIn("presupuesto total", texto)
        self.assertEqual(cliente.peticiones, [])
        self.assertIsNone(agente._presupuesto_usuario())

    def test_no_reutiliza_presupuesto_anterior(self):
        agente, _ = self.crear()
        agente.historial.append({"role": "user", "content": "Tenemos 500 EUR en total."})
        agente.responder("Ahora tenemos 1400.")
        self.assertIsNone(agente._presupuesto_usuario())
        self.assertIn("presupuesto", agente._faltan_datos_imprescindibles())

    def test_confirmacion_conserva_viaje_y_coste_verificado(self):
        agente, cliente = self.crear([coste("lisboa"), propuesta(["lisboa"], "recomendacion", 1400)])
        peticion = "Somos dos personas, cuatro días desde Madrid, nos gusta la cultura y tenemos 1400."
        agente.responder(peticion)
        texto = agente.responder("1400 EUR en total. Recomienda un destino.")
        self.assertIn("910 EUR", texto)
        self.assertIn("490 EUR", texto)
        self.assertIn("Intereses: cultura", texto)
        self.assertEqual(cliente.peticiones[0][1]["content"], peticion)

    def test_si_sin_moneda_no_confirma_importe(self):
        agente, cliente = self.crear()
        agente.responder("Tenemos 1400")
        self.assertIn("Confirma el importe", agente.responder("Sí"))
        self.assertEqual(cliente.peticiones, [])

    def test_dias_y_viajeros_no_son_presupuestos(self):
        for texto in ("Tenemos 4 días", "Tenemos 2 viajeros", "Tenemos 3 destinos", "Somos 2 personas, 4 días"):
            with self.subTest(texto=texto):
                self.assertEqual(AgenteViajes._menciones_presupuesto(texto), [])

    def test_formatos_y_actualizacion_explicita(self):
        for importe in ("1400 €", "1.400 EUR", "1.400,00 euros"):
            with self.subTest(importe=importe):
                agente, _ = self.crear()
                agente.historial.extend([
                    {"role": "user", "content": "500 EUR"},
                    {"role": "user", "content": "Ahora tenemos " + importe + " en total."},
                ])
                self.assertEqual(agente._presupuesto_usuario(), 1400)

    def test_menciones_internas_no_confirman_presupuesto(self):
        agente, _ = self.crear()
        agente.responder("Presupuesto máximo: 1400")
        agente.historial.append({"role": "user", "interno": True, "content": "1400 EUR"})
        self.assertIsNone(agente._presupuesto_usuario())

    def test_tres_recomendaciones_tras_confirmar(self):
        agente, _ = self.crear([
            coste("lisboa"), coste("oporto"), coste("barcelona"),
            propuesta(["lisboa", "oporto", "barcelona"], "recomendacion", 1400),
        ])
        agente.responder("Somos dos personas, cuatro días desde Madrid, cultura y tenemos 1400. Recomienda hasta tres destinos.")
        texto = agente.responder("1400 € en total")
        self.assertLess(texto.index("| Oporto"), texto.index("| Lisboa"))
        self.assertLess(texto.index("| Lisboa"), texto.index("| Barcelona"))
        self.assertIn("630 EUR", texto)


class TestPreguntasRepetidas(unittest.TestCase):
    def test_pregunta_repetida_usa_solo_datos_pendientes(self):
        saludo = {"role": "assistant", "content": "Hola. ¿Origen, duración, viajeros y presupuesto?"}
        cliente = ClienteSimulado([saludo, saludo])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        agente.responder("hola")
        respuesta = agente.responder("Quiero hacer un viaje para 4 personas en febrero del 2027")
        self.assertIn("origen, duración, presupuesto", respuesta)
        self.assertNotIn("viajeros", respuesta)
        self.assertEqual(len(cliente.peticiones), 2)
        self.assertIn("febrero del 2027", agente.historial[-2]["content"])

    def test_resumen_pendientes_respeta_datos_de_turnos_anteriores(self):
        saludo = {"role": "assistant", "content": "¿Cuáles son los datos del viaje?"}
        cliente = ClienteSimulado([saludo, saludo])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        agente.responder("Somos 4 personas y salimos desde Madrid en febrero de 2027")
        respuesta = agente.responder("Viajaremos 5 días")
        self.assertIn("faltan estos datos: presupuesto.", respuesta)
        self.assertNotIn("origen,", respuesta)
        self.assertEqual(len(cliente.peticiones), 2)

    def test_no_sustituye_una_pregunta_nueva(self):
        cliente = ClienteSimulado([
            {"role": "assistant", "content": "¿Cuántos viajeros?"},
            {"role": "assistant", "content": "¿Cuántos días queréis viajar?"},
        ])
        agente = AgenteViajes(cliente, mostrar=lambda texto: None)
        agente.responder("hola")
        self.assertEqual(agente.responder("4 personas, en febrero"), "¿Cuántos días queréis viajar?")


class TestAclaracionSinBucles(unittest.TestCase):
    def test_pregunta_por_moneda_sin_importes_es_valida(self):
        cliente = ClienteSimulado([{"role": "assistant", "content": "¿Cuál es tu presupuesto total en euros?"}])
        respuesta = AgenteViajes(cliente, mostrar=lambda t: None).responder("hola")
        self.assertEqual(respuesta, "¿Cuál es tu presupuesto total en euros?")
        self.assertEqual(len(cliente.peticiones), 1)

    def test_hola_no_agota_turno_si_modelo_inventa_presupuesto(self):
        cliente = ClienteSimulado([propuesta(["oporto"], "recomendacion", 800)] * 2)
        agente = AgenteViajes(cliente, mostrar=lambda t: None)
        respuesta = agente.responder("hola")
        self.assertIn("origen, duración, viajeros, presupuesto", respuesta)
        self.assertNotIn("límite", respuesta)
        self.assertNotIn("800", respuesta)
        self.assertEqual(len(cliente.peticiones), 2)

    def test_aclaracion_conserva_viajeros_y_mes(self):
        cliente = ClienteSimulado([{"role": "assistant", "content": "Te recomiendo destinos con precios sin comprobar."}] * 2)
        agente = AgenteViajes(cliente, mostrar=lambda t: None)
        respuesta = agente.responder("quiero ahcer un viaje de 4 personas en febrero del 2027")
        self.assertIn("origen, duración, presupuesto", respuesta)
        self.assertNotIn("viajeros", respuesta)
        self.assertIn("febrero del 2027", agente.historial[1]["content"])
        self.assertEqual(len(cliente.peticiones), 2)

    def test_importe_no_se_permite_por_tener_interrogacion(self):
        agente = AgenteViajes(mostrar=lambda t: None)
        for texto in ("¿Tu presupuesto es 800 euros?", "¿Lisboa cuesta 800 EUR?", "¿Te recomiendo Lisboa?"):
            with self.subTest(texto=texto):
                respuesta, error = agente._validar_respuesta({"role": "assistant", "content": texto})
                self.assertIsNotNone(error)
                self.assertIsNone(respuesta)


if __name__ == "__main__":
    unittest.main()
