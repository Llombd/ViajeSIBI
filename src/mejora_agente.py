"""Ciclo acotado: proponer una política de memoria, probarla y conservar evidencia.

Inspirado en el aprendizaje del arnés; no ejecuta Harness² ni modifica código/modelos.
"""
from datetime import date, datetime, timezone
import hashlib
import json
from math import isfinite
from pathlib import Path
from time import monotonic
from uuid import uuid4

from src.agent import ErrorOllama
from src.ofertas_reales import ErrorOfertas
from src.seleccion_viaje import proponer_busquedas, decidir_siguiente_busqueda, explorar_ofertas
from src.memoria_busquedas import contexto_viaje

# Casos fijados antes de probar políticas. Las dos últimas fechas no se usan para aprender.
PRACTICA = ((date(2027, 2, 1), date(2027, 2, 4)), (date(2027, 2, 8), date(2027, 2, 11)))
VALIDACION = ((date(2027, 2, 15), date(2027, 2, 18)), (date(2027, 2, 22), date(2027, 2, 25)))
CONTEXTO_LAB = contexto_viaje("VLC", 2, 3, "cultura")
PRESUPUESTO_LAB = 500


class ClienteMedido:
    def __init__(self, cliente):
        self.cliente = cliente
        self.llamadas = 0

    def consultar_json(self, mensajes, formato):
        self.llamadas += 1
        return self.cliente.consultar_json(mensajes, formato)


def ejecutar_caso(cliente, consultar, periodo, experiencia=(), *, origen="VLC", adultos=2,
                  presupuesto=500, gustos="cultura"):
    inicio = monotonic()
    cliente = ClienteMedido(cliente)
    observaciones, registro, planes = [], [], []
    error = None
    try:
        propuestas = proponer_busquedas(cliente, origen, [periodo], gustos, adultos, presupuesto,
                                       experiencia=experiencia)
        planes, registro, _ = explorar_ofertas(
            consultar, origen, propuestas, adultos, presupuesto,
            replantear=lambda datos: decidir_siguiente_busqueda(
                cliente, origen, [periodo], gustos, adultos, presupuesto, datos, propuestas),
            fechas=[periodo], observaciones=observaciones, limite_intentos=3,
            conservar_pendientes=True, limite_total=presupuesto, objetivo_opciones=1,
        )
    except (ErrorOllama, ErrorOfertas) as exc:
        error = str(exc)
    validos = [p for p in planes if p.get("impuestos_confirmados") and p["total"] <= presupuesto]
    return {
        "ida": periodo[0].isoformat(), "vuelta": periodo[1].isoformat(),
        "viaje_encontrado": bool(validos), "total": min((p["total"] for p in validos), default=None),
        "consultas": sum(o["consultas_proveedor"] for o in observaciones),
        "llamadas_modelo": cliente.llamadas, "segundos": round(monotonic() - inicio, 2),
        "error": error, "revisiones_invalidas": sum(o.get("revision_estado") == "invalida" for o in observaciones),
        "observaciones": observaciones, "traza": registro,
        "memoria_usada": list(experiencia),
    }


class AgenteMejora:
    """Segundo rol de Qwen3. Solo propone una política permitida y cita evidencia."""
    def __init__(self, cliente):
        self.cliente = cliente

    def proponer(self, experiencia):
        if not experiencia:
            return {"estrategia": "mantener", "evidencias": [], "hipotesis": "No hay experiencia repetida suficiente."}
        codigos = [e["aeropuerto"] for e in experiencia]
        formato = {"type": "object", "additionalProperties": False, "properties": {
            "estrategia": {"type": "string", "enum": ["priorizar_exitos", "mantener"]},
            "evidencias": {"type": "array", "items": {"type": "string", "enum": codigos}, "maxItems": 3},
        }, "required": ["estrategia", "evidencias"]}
        texto = self.cliente.consultar_json([
            {"role": "system", "content": (
                "Eres el agente de mejora. Revisa la experiencia histórica de viajes comparables. "
                "Puedes proponer priorizar_exitos: dar al planificador evidencia de destinos que encajaron "
                "repetidamente y presentarlos primero en la lista de candidatos. El modelo seguirá eligiendo "
                "y se comprobarán precios actuales. Tu tarea es proponer un experimento, no aprobarlo. "
                "Con dos o más éxitos comparables, plantea priorizar_exitos como hipótesis que merece probarse; "
                "elige mantener si la evidencia no respalda ese cambio. La falta de garantía por sí sola "
                "no impide probar una hipótesis: el evaluador decidirá después. "
                "Cita solo códigos presentes en la evidencia. No afirmes que la mejora funcionará: se probará "
                "en fechas reservadas. No cambies presupuesto, fechas, gustos, herramientas ni validaciones. /no_think"
            )}, {"role": "user", "content": json.dumps(experiencia, ensure_ascii=False)}], formato)
        try:
            propuesta = json.loads(texto)
            if (set(propuesta) != {"estrategia", "evidencias"}
                    or propuesta["estrategia"] not in ("priorizar_exitos", "mantener")
                    or not isinstance(propuesta["evidencias"], list)
                    or any(c not in codigos for c in propuesta["evidencias"])
                    or (propuesta["estrategia"] == "priorizar_exitos" and not propuesta["evidencias"])):
                raise ValueError
        except (ValueError, TypeError):
            raise ErrorOllama("El agente de mejora no devolvió una política respaldada por la experiencia.") from None
        return {**propuesta, "hipotesis": (
            "Comprobar primero destinos con éxitos repetidos puede encontrar un viaje con menos consultas. "
            "Los precios históricos no garantizan los actuales."
            if propuesta["estrategia"] == "priorizar_exitos" else "El modelo propone mantener la estrategia.")}


def validar_mejora(pares, presupuesto=PRESUPUESTO_LAB):
    """Criterio publicado antes del experimento; no usa un juicio favorable del modelo."""
    # Una etiqueta de éxito no basta: las métricas también deben ser coherentes.
    try:
        for par in pares:
            for clave in ("sin_memoria", "con_memoria"):
                r = par[clave]
                if type(r["viaje_encontrado"]) is not bool:
                    raise ValueError
                if date.fromisoformat(r["ida"]) >= date.fromisoformat(r["vuelta"]):
                    raise ValueError
                for campo in ("consultas", "llamadas_modelo"):
                    if type(r[campo]) is not int or r[campo] < 0:
                        raise ValueError
                total = r["total"]
                if r["viaje_encontrado"]:
                    if type(total) not in (int, float) or not isfinite(total) or not 0 < total <= presupuesto:
                        raise ValueError
                elif total is not None:
                    raise ValueError
    except (KeyError, TypeError, ValueError):
        return False, "Las mediciones están incompletas o no respetan el presupuesto y las fechas."
    if len(pares) < 2 or len({p.get("sin_memoria", {}).get("ida") for p in pares}) < 2:
        return False, "Faltan al menos dos fechas distintas de validación."
    mejora = False
    for par in pares:
        base, nueva = par["sin_memoria"], par["con_memoria"]
        if (base.get("error") or nueva.get("error") or base.get("revisiones_invalidas")
                or nueva.get("revisiones_invalidas") or base["ida"] != nueva["ida"]
                or base["vuelta"] != nueva["vuelta"]):
            return False, "Hay errores o condiciones de comparación incompatibles."
        if not nueva["viaje_encontrado"]:
            return False, "La candidata no resolvió todos los casos reservados."
        if nueva["consultas"] > base["consultas"] or nueva["llamadas_modelo"] > base["llamadas_modelo"]:
            return False, "La candidata necesitó más consultas en algún caso."
        if base["viaje_encontrado"] and nueva["total"] > base["total"]:
            return False, "La candidata encontró una opción más cara en algún caso."
        mejora |= (not base["viaje_encontrado"] or nueva["consultas"] < base["consultas"]
                   or nueva["llamadas_modelo"] < base["llamadas_modelo"]
                   or (base["total"] is not None and nueva["total"] < base["total"]))
    return (True, "Resuelve los casos reservados sin empeorar coste ni consultas y mejora al menos una medida.") if mejora else (
        False, "Empate: no se cambia la estrategia sin una mejora medida.")


def practicar(cliente, consultar, memoria, progreso=lambda texto: None):
    resultados = []
    for numero, periodo in enumerate(PRACTICA, 1):
        progreso(f"Práctica {numero}/2: el planificador busca un viaje sin experiencia previa.")
        resultado = ejecutar_caso(cliente, consultar, periodo)
        resultados.append(resultado)
        if not resultado["error"]:
            memoria.registrar(CONTEXTO_LAB, resultado["observaciones"])
    return resultados


def experimentar(cliente, consultar, memoria, progreso=lambda texto: None):
    experiencia = memoria.recordar(CONTEXTO_LAB, PRESUPUESTO_LAB)
    progreso("El agente de mejora propone una política a partir de la experiencia guardada.")
    propuesta = AgenteMejora(cliente).proponer(experiencia)
    informe = {"id": uuid4().hex, "contexto": CONTEXTO_LAB, "fuente": "ficticio-v1",
               "fecha_utc": datetime.now(timezone.utc).isoformat(), "modelo": "qwen3:4b",
               "propuesta": propuesta, "experiencia": experiencia, "validacion": [],
               "limites": {"intentos_por_caso": 3, "objetivo_opciones": 1, "presupuesto": PRESUPUESTO_LAB},
               "codigo_sha256": {}}
    for nombre in ("mejora_agente.py", "seleccion_viaje.py", "demo_ofertas.py"):
        informe["codigo_sha256"][nombre] = hashlib.sha256(Path(__file__).with_name(nombre).read_bytes()).hexdigest()
    if propuesta["estrategia"] == "priorizar_exitos":
        seleccionada = [e for e in experiencia if e["aeropuerto"] in propuesta["evidencias"]]
        # Se congela la memoria: ninguna respuesta de validación se usa para aprender.
        for numero, periodo in enumerate(VALIDACION, 1):
            progreso(f"Fecha reservada {numero}/2: ejecutar sin memoria y con la política propuesta.")
            # Alternar el orden reduce el sesgo por el calentamiento del modelo local.
            par = {}
            orden = (False, True) if numero == 1 else (True, False)
            for con_memoria in orden:
                par["con_memoria" if con_memoria else "sin_memoria"] = ejecutar_caso(
                    cliente, consultar, periodo, seleccionada if con_memoria else ())
            informe["validacion"].append(par)
    return memoria.guardar_experimento(informe)
