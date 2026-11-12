"""Separación de datos, aprendizaje persistente y rechazo de mejoras no demostradas."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from src.agent import ErrorOllama
from src.memoria_busquedas import MemoriaBusquedas, contexto_viaje
from src.mejora_agente import AgenteMejora, validar_mejora, ejecutar_caso, experimentar, CONTEXTO_LAB, VALIDACION
from src.demo_ofertas import consultar_catalogo_ficticio


def resultado(dia, consultas=8, total=480, **extras):
    return dict(ida=f"2027-02-{dia:02d}", vuelta=f"2027-02-{dia+3:02d}", consultas=consultas,
                llamadas_modelo=consultas//4, viaje_encontrado=total is not None, total=total,
                error=None, revisiones_invalidas=0, **extras)


def pares():
    return [{"sin_memoria": resultado(d), "con_memoria": resultado(d, consultas=4)} for d in (15, 22)]


class TestMejoraAgente(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ruta = Path(self.temp.name)/"memoria.sqlite3"
        self.memoria = MemoriaBusquedas(self.ruta)

    def registrar(self):
        self.memoria.registrar(CONTEXTO_LAB, [
            dict(aeropuerto="BCN", ida=f"2027-02-{d:02d}", vuelta=f"2027-02-{d+3:02d}",
                 total=480, impuestos_confirmados=True) for d in (1, 8)])

    def test_exige_repeticion_y_no_duplica_misma_fecha(self):
        dato = dict(aeropuerto="BCN", ida="2027-02-01", vuelta="2027-02-04", total=480, impuestos_confirmados=True)
        self.memoria.registrar(CONTEXTO_LAB, [dato, dato])
        self.assertEqual(self.memoria.recordar(CONTEXTO_LAB, 500), [])
        self.registrar()
        recordado = MemoriaBusquedas(self.ruta).recordar(CONTEXTO_LAB, 500)
        self.assertEqual(recordado[0]["observaciones"], 2)

    def test_fuentes_origen_gustos_y_filtros_no_se_mezclan(self):
        self.registrar()
        for contexto in (contexto_viaje("VLC", 2, 3, "cultura", fuente="real"),
                         contexto_viaje("MAD", 2, 3, "cultura"), contexto_viaje("VLC", 2, 3, "playa"),
                         contexto_viaje("VLC", 2, 4, "cultura"), contexto_viaje("VLC", 2, 3, "cultura", nota=4)):
            self.assertEqual(self.memoria.recordar(contexto, 500), [])

    def test_presupuesto_menor_no_reutiliza_exito_caro(self):
        self.registrar()
        self.assertEqual(self.memoria.recordar(CONTEXTO_LAB, 400), [])

    def test_no_aprende_precios_provisionales_ausentes_o_invalidos(self):
        base = dict(aeropuerto="BCN", ida="2027-02-01", vuelta="2027-02-04", total=480)
        self.memoria.registrar(CONTEXTO_LAB, [base, dict(base, impuestos_confirmados=False),
                                           dict(base, impuestos_confirmados=True, total=float("nan"))])
        self.assertEqual(self.memoria.recordar(CONTEXTO_LAB, 500), [])

    def test_agente_mejora_cita_solo_evidencias_reales(self):
        self.registrar()
        cliente = Mock()
        cliente.consultar_json.return_value = '{"estrategia":"priorizar_exitos","evidencias":["BCN"]}'
        propuesta = AgenteMejora(cliente).proponer(self.memoria.recordar(CONTEXTO_LAB, 500))
        self.assertEqual(propuesta["estrategia"], "priorizar_exitos")
        datos = json.loads(cliente.consultar_json.call_args.args[0][1]["content"])
        self.assertEqual(datos[0]["observaciones"], 2)
        for respuesta in ('{"estrategia":"editar_codigo","evidencias":["BCN"]}',
                          '{"estrategia":"priorizar_exitos","evidencias":["MAD"]}',
                          '{"estrategia":"priorizar_exitos","evidencias":[]}'):
            cliente.consultar_json.return_value = respuesta
            with self.assertRaises(ErrorOllama):
                AgenteMejora(cliente).proponer(datos)

    def test_sin_experiencia_no_inventa_hipotesis(self):
        cliente = Mock()
        self.assertEqual(AgenteMejora(cliente).proponer([])["estrategia"], "mantener")
        cliente.consultar_json.assert_not_called()

    def test_acepta_mejora_y_rechaza_empate_coste_y_errores(self):
        self.assertTrue(validar_mejora(pares())[0])
        for cambios in ({"consultas": 9}, {"total": 490}, {"error": "Sin modelo"},
                        {"viaje_encontrado": False, "total": None}, {"revisiones_invalidas": 1}):
            datos = pares()
            datos[1]["con_memoria"].update(cambios)
            self.assertFalse(validar_mejora(datos)[0])
        empate = [{"sin_memoria": resultado(d), "con_memoria": resultado(d)} for d in (15,22)]
        self.assertFalse(validar_mejora(empate)[0])
        self.assertFalse(validar_mejora(pares()[:1])[0])

    def test_aprendizaje_persiste_y_un_rechazo_no_sobrescribe_la_version_anterior(self):
        self.registrar()
        informe = dict(id="aprobado", contexto=CONTEXTO_LAB, fuente="ficticio-v1",
                       propuesta={"estrategia":"priorizar_exitos", "evidencias":["BCN"]}, validacion=pares(),
                       experiencia=self.memoria.recordar(CONTEXTO_LAB,500))
        self.assertTrue(self.memoria.guardar_experimento(informe)["adoptada"])
        self.assertEqual(MemoriaBusquedas(self.ruta).activa(CONTEXTO_LAB)["experimento"], "aprobado")
        informe.update(id="rechazado", validacion=[], adoptada=True)
        self.assertFalse(self.memoria.guardar_experimento(informe)["adoptada"])
        self.assertEqual(self.memoria.activa(CONTEXTO_LAB)["experimento"], "aprobado")
        self.assertEqual(len(self.memoria.experimentos(CONTEXTO_LAB)), 2)
        self.assertIsNone(self.memoria.activa(contexto_viaje("VLC",2,3,"cultura",fuente="real")))

    def test_la_memoria_no_es_un_precio_y_se_consulta_de_nuevo(self):
        cliente = Mock()
        cliente.consultar_json.return_value = '{"busquedas":[{"aeropuerto":"BCN","fechas":0}]}'
        proveedor = Mock(side_effect=consultar_catalogo_ficticio)
        experiencia = [{"aeropuerto":"BCN", "media_historica":1, "observaciones":2}]
        r = ejecutar_caso(cliente, proveedor, (date(2027,2,15),date(2027,2,18)), experiencia)
        self.assertEqual(r["total"],480)
        self.assertEqual(proveedor.call_count,4)
        self.assertEqual(r["llamadas_modelo"],1)  # El objetivo de una opción evita revisiones innecesarias.
        contenido=json.loads(cliente.consultar_json.call_args.args[0][1]["content"])
        self.assertEqual(contenido["experiencia_historica"],experiencia)

    def test_las_respuestas_de_validacion_no_entran_en_memoria(self):
        self.registrar()
        antes=self.memoria.recordar(CONTEXTO_LAB,500)
        with patch("src.mejora_agente.AgenteMejora.proponer", return_value={"estrategia":"priorizar_exitos", "evidencias":["BCN"]}), \
             patch("src.mejora_agente.ejecutar_caso", side_effect=[resultado(15),resultado(15,4),resultado(22,4),resultado(22)]):
            informe=experimentar(Mock(),Mock(),self.memoria)
        self.assertTrue(informe["adoptada"])
        self.assertEqual(self.memoria.recordar(CONTEXTO_LAB,500),antes)

    def test_error_del_modelo_no_produce_exito_ni_coste_falso(self):
        cliente=Mock()
        cliente.consultar_json.side_effect=ErrorOllama("Sin modelo")
        proveedor=Mock()
        r=ejecutar_caso(cliente,proveedor,VALIDACION[0])
        self.assertFalse(r["viaje_encontrado"])
        self.assertEqual(r["error"],"Sin modelo")
        proveedor.assert_not_called()

    def test_fuente_incompatible_no_activa_estrategia(self):
        with self.assertRaises(ValueError):
            self.memoria.guardar_experimento(dict(id="mezcla", contexto=CONTEXTO_LAB, fuente="real",
                propuesta={"estrategia":"priorizar_exitos"}, validacion=pares()))
        self.assertIsNone(self.memoria.activa(CONTEXTO_LAB))

    def test_contaminacion_de_validacion_impide_adopcion(self):
        informe = self.memoria.guardar_experimento(dict(id="contaminado", contexto=CONTEXTO_LAB,
            fuente="ficticio-v1", propuesta={"estrategia":"priorizar_exitos"}, validacion=pares(),
            experiencia=[{"fechas_observadas":["2027-02-15"]}]))
        self.assertFalse(informe["adoptada"])
        self.assertIn("contaminada",informe["motivo_validacion"])
        self.assertIsNone(self.memoria.activa(CONTEXTO_LAB))

    def test_esquema_limita_codigos_y_fechas_antes_de_generar(self):
        from src.seleccion_viaje import proponer_busquedas
        cliente=Mock()
        cliente.consultar_json.return_value='{"busquedas":[{"aeropuerto":"BCN","fechas":0}]}'
        proponer_busquedas(cliente,"VLC",[VALIDACION[0]],"cultura",2,500)
        esquema=cliente.consultar_json.call_args.args[1]["properties"]["busquedas"]["items"]["properties"]
        self.assertEqual(esquema["fechas"]["enum"],[0])
        self.assertNotIn("VLC",esquema["aeropuerto"]["enum"])

    def test_fechas_con_otras_noches_no_contaminan_contexto(self):
        with self.assertRaises(ValueError):
            self.memoria.registrar(CONTEXTO_LAB,[dict(aeropuerto="BCN",ida="2027-02-01",vuelta="2027-02-10",
                impuestos_confirmados=True,total=480)])

    def test_media_barata_no_oculta_un_fracaso_caro(self):
        self.registrar()
        self.memoria.registrar(CONTEXTO_LAB, [dict(aeropuerto="BCN", ida="2027-02-08",
            vuelta="2027-02-11", total=510, impuestos_confirmados=True)])
        self.assertEqual(self.memoria.recordar(CONTEXTO_LAB, 500), [])

    def test_no_activa_estrategia_sin_evidencia_guardada(self):
        informe = self.memoria.guardar_experimento(dict(id="sin_practica", contexto=CONTEXTO_LAB,
            fuente="ficticio-v1", propuesta={"estrategia":"priorizar_exitos", "evidencias":["BCN"]},
            validacion=pares(), experiencia=[]))
        self.assertFalse(informe["adoptada"])
        self.assertIsNone(self.memoria.activa(CONTEXTO_LAB))

    def test_siguiente_viaje_usa_solo_la_memoria_validada(self):
        self.registrar()
        original = self.memoria.recordar(CONTEXTO_LAB, 500)
        self.memoria.guardar_experimento(dict(id="validada", contexto=CONTEXTO_LAB, fuente="ficticio-v1",
            propuesta={"estrategia":"priorizar_exitos", "evidencias":["BCN"]},
            experiencia=original, validacion=pares()))
        self.memoria.registrar(CONTEXTO_LAB, [dict(aeropuerto="LIS", ida=f"2027-02-{d:02d}",
            vuelta=f"2027-02-{d+3:02d}", total=300, impuestos_confirmados=True) for d in (1,8)])
        self.assertEqual(len(self.memoria.recordar(CONTEXTO_LAB,500)),2)
        self.assertEqual(self.memoria.experiencia_validada(CONTEXTO_LAB,500),original)
        self.assertEqual(self.memoria.experiencia_validada(CONTEXTO_LAB,400),[])

    def test_no_aprueba_metricas_incoherentes_o_fuera_de_presupuesto(self):
        for cambio in ({"total":float("nan")}, {"total":501}, {"consultas":-1},
                       {"viaje_encontrado":True,"total":None}, {"vuelta":"2027-02-01"}):
            datos = pares()
            datos[0]["con_memoria"].update(cambio)
            self.assertFalse(validar_mejora(datos)[0])
