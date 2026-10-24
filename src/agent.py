"""Bucle explícito con Ollama local, sin SDK ni dependencias externas."""

import copy
import inspect
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.prompts import INSTRUCCIONES
from src.tools import (buscar_destinos, consultar_destino, estimar_coste,
                       _cargar_catalogo, _normalizar)


FUNCIONES = {
    "buscar_destinos": buscar_destinos,
    "consultar_destino": consultar_destino,
    "estimar_coste": estimar_coste,
}


def _definir_herramienta(nombre, descripcion, propiedades, obligatorios):
    return {
        "type": "function",
        "function": {
            "name": nombre,
            "description": descripcion,
            "parameters": {
                "type": "object",
                "properties": propiedades,
                "required": obligatorios,
                "additionalProperties": False,
            },
        },
    }


HERRAMIENTAS = [
    _definir_herramienta(
        "buscar_destinos",
        "Busca destinos del catálogo ficticio. Los filtros son opcionales. "
        "Todos los intereses enviados deben coincidir; no enviar intereses no indicados.",
        {
            "region": {"type": "string", "description": "sur, oeste, centro o norte; omitir si no hay filtro."},
            "intereses": {"type": "array", "items": {"type": "string"},
                          "description": "Solo intereses explícitos del usuario: cultura, gastronomia, playa o naturaleza. Omitir si no indicó ninguno."},
        },
        [],
    ),
    _definir_herramienta(
        "consultar_destino",
        "Consulta actividades y clima mensual ficticio de un destino.",
        {
            "destino_id": {"type": "string", "description": "Identificador del catálogo."},
            "mes": {"type": "integer", "minimum": 1, "maximum": 12},
        },
        ["destino_id", "mes"],
    ),
    _definir_herramienta(
        "estimar_coste",
        "Calcula coste ficticio total del grupo: transporte, alojamiento y gastos diarios.",
        {
            "destino_id": {"type": "string"},
            "origen": {"type": "string", "description": "Solo Madrid tiene datos."},
            "duracion_dias": {"type": "integer", "minimum": 1},
            "viajeros": {"type": "integer", "minimum": 1},
        },
        ["destino_id", "origen", "duracion_dias", "viajeros"],
    ),
]


FORMATO_PROPUESTA = {
    "type": "object",
    "properties": {
        "tipo": {"type": "string", "enum": ["recomendacion", "coste"]},
        "destinos": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
        "origen": {"type": "string"},
        "duracion_dias": {"type": "integer", "minimum": 1},
        "viajeros": {"type": "integer", "minimum": 1},
        "presupuesto_total": {"type": ["number", "null"]},
    },
    "required": ["tipo", "destinos", "origen", "duracion_dias", "viajeros", "presupuesto_total"],
    "additionalProperties": False,
}

FORMATO_DECISION = {
    "type": "object",
    "properties": {
        "herramienta": {"type": "string", "enum": ["ninguna", *FUNCIONES]},
        "argumentos": {"anyOf": [
            herramienta["function"]["parameters"] for herramienta in HERRAMIENTAS
        ] + [FORMATO_PROPUESTA]},
        "respuesta": {"type": "string"},
    },
    "required": ["herramienta", "argumentos", "respuesta"],
    "additionalProperties": False,
}


class ErrorOllama(RuntimeError):
    """Fallo de conexión o respuesta inválida del servidor local."""


class ClienteOllama:
    def __init__(self, modelo="qwen3:4b"):
        self.modelo = modelo

    def chat(self, mensajes):
        # Enviamos descripciones, no una secuencia de acciones.
        mensajes_api = [dict(mensaje) for mensaje in mensajes]
        if not mensajes_api or mensajes_api[0].get("role") != "system":
            mensajes_api.insert(0, {"role": "system", "content": INSTRUCCIONES})
        for mensaje in mensajes_api:
            mensaje.pop("interno", None)
            if mensaje.get("tool_calls"):
                # Conserva el mismo protocolo JSON al reenviar las decisiones.
                funcion = mensaje.pop("tool_calls")[0]["function"]
                mensaje["content"] = json.dumps({
                    "herramienta": funcion["name"],
                    "argumentos": funcion.get("arguments", {}),
                    "respuesta": "",
                }, ensure_ascii=False)
            elif mensaje.get("role") == "assistant":
                mensaje["content"] = json.dumps({
                    "herramienta": "ninguna", "argumentos": mensaje.get("propuesta", {}),
                    "respuesta": mensaje["content"],
                }, ensure_ascii=False)
            elif mensaje.get("role") == "tool":
                # En este protocolo no dependemos de la plantilla de tools nativas.
                nombre = mensaje.pop("tool_name")
                mensaje["role"] = "user"
                mensaje["content"] = (
                    f"Resultado de {nombre}: {mensaje['content']}\n"
                    "Este es un resultado del programa, no una nueva petición. "
                    "Si ya basta, elige ninguna y responde al usuario. "
                    "No repitas una consulta cuyo resultado ya tienes."
                )
        mensajes_api[0] = {
            "role": "system",
            "content": mensajes_api[0]["content"] + "\nHerramientas disponibles:\n"
            + json.dumps(HERRAMIENTAS, ensure_ascii=False)
            + "\nFormato de decisión:\n" + json.dumps(FORMATO_DECISION),
        }
        datos = {
            "model": self.modelo,
            "messages": mensajes_api,
            "format": FORMATO_DECISION,
            "stream": False,
            "think": False,
            # Contexto moderado para el Mac de 8 GB; salida breve.
            "options": {"num_ctx": 8192, "num_predict": 1024, "temperature": 0.2},
        }
        peticion = Request(
            "http://localhost:11434/api/chat",
            data=json.dumps(datos, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(peticion, timeout=120) as respuesta:
                datos_respuesta = json.load(respuesta)
        except HTTPError as error:
            detalle = error.read().decode("utf-8", errors="replace")[:500]
            raise ErrorOllama(
                f"Ollama devolvió HTTP {error.code}: {detalle}. "
                "Comprueba el modelo con ollama list y la versión de Ollama."
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ErrorOllama(
                "No se pudo consultar Ollama local. Abre Ollama o ejecuta "
                "ollama serve. La petición tiene un límite de 120 segundos."
            ) from error
        except (ValueError, UnicodeError) as error:
            raise ErrorOllama("Ollama devolvió una respuesta que no es JSON válido.") from error

        if isinstance(datos_respuesta, dict) and datos_respuesta.get("done_reason") == "length":
            raise ErrorOllama(
                "El modelo alcanzó el límite de salida sin completar su respuesta. "
                "Prueba una petición más concreta; revisa la compatibilidad de think: false."
            )
        mensaje = datos_respuesta.get("message") if isinstance(datos_respuesta, dict) else None
        if not isinstance(mensaje, dict) or mensaje.get("role") != "assistant":
            raise ErrorOllama("Ollama no devolvió un mensaje de asistente válido.")
        if not isinstance(mensaje.get("content", ""), str):
            raise ErrorOllama("El contenido de Ollama no es texto.")
        try:
            decision = json.loads(mensaje.get("content", ""))
        except ValueError as error:
            raise ErrorOllama("El modelo no devolvió una decisión JSON válida.") from error
        if (
            not isinstance(decision, dict)
            or set(decision) != {"herramienta", "argumentos", "respuesta"}
            or decision["herramienta"] not in ["ninguna", *FUNCIONES]
            or not isinstance(decision["argumentos"], dict)
            or not isinstance(decision["respuesta"], str)
        ):
            raise ErrorOllama("La decisión del modelo tiene un formato inválido.")
        # Convertimos la decisión al formato interno de historial del bucle.
        # No guardamos ni mostramos el campo thinking.
        if decision["herramienta"] == "ninguna":
            return {"role": "assistant", "content": decision["respuesta"],
                    "propuesta": decision["argumentos"]}
        return {
            "role": "assistant", "content": "",
            "tool_calls": [{"function": {
                "name": decision["herramienta"], "arguments": decision["argumentos"],
            }}],
        }


def ejecutar_herramienta(nombre, argumentos):
    """Lista permitida + comprobación de firma + validaciones de tools.py."""
    if nombre not in FUNCIONES:
        return {"error": f"Herramienta no permitida: {nombre}."}
    if not isinstance(argumentos, dict):
        return {"error": "Los argumentos deben ser un objeto JSON."}
    funcion = FUNCIONES[nombre]
    try:
        inspect.signature(funcion).bind(**argumentos)
    except TypeError:
        return {"error": "Faltan argumentos obligatorios o hay argumentos desconocidos."}
    try:
        return funcion(**argumentos)
    except (OSError, ValueError, KeyError):
        return {"error": "No se pudo leer el catálogo local o sus datos no son válidos."}


class AgenteViajes:
    def __init__(self, cliente=None, mostrar=print, max_consultas=12, max_herramientas=10):
        if type(max_consultas) is not int or max_consultas < 1:
            raise ValueError("max_consultas debe ser un entero positivo.")
        if type(max_herramientas) is not int or max_herramientas < 1:
            raise ValueError("max_herramientas debe ser un entero positivo.")
        self.cliente = cliente if cliente is not None else ClienteOllama()
        self.mostrar = mostrar
        self.max_consultas = max_consultas
        self.max_herramientas = max_herramientas
        self.historial = [{"role": "system", "content": INSTRUCCIONES
                          + f"\nLímites: {max_consultas} consultas al modelo y "
                          + f"{max_herramientas} intentos de herramientas por turno."}]

    def responder(self, texto):
        if not isinstance(texto, str) or not texto.strip():
            raise ValueError("Escribe una petición no vacía.")
        inicio = len(self.historial)
        self.historial.append({"role": "user", "content": texto})
        ejecuciones = 0
        try:
            for _ in range(self.max_consultas):
                mensaje = copy.deepcopy(self.cliente.chat(self.historial))
                self.historial.append(mensaje)
                llamadas = mensaje.get("tool_calls", [])
                if not llamadas:
                    if mensaje.get("content", "").strip() or mensaje.get("propuesta"):
                        respuesta, error = self._validar_respuesta(mensaje)
                        if error:
                            # No conservar una recomendación inventada como si fuera válida.
                            self.historial.pop()
                            self.historial.append({
                                "role": "user", "interno": True,
                                "content": "Validación del programa: " + error
                                + " Elige tú las consultas necesarias o pide una aclaración.",
                            })
                            self.mostrar("[Validación] Respuesta bloqueada: " + error)
                            continue
                        mensaje["content"] = respuesta
                        return respuesta
                    return self._terminar("El modelo devolvió una respuesta vacía. Reformula la petición.")

                limite = False
                for llamada in llamadas:
                    funcion = llamada["function"]
                    nombre = funcion["name"]
                    argumentos = funcion.get("arguments", {})
                    if nombre == "buscar_destinos" and isinstance(argumentos, dict):
                        argumentos = self._ajustar_filtros_busqueda(argumentos)
                        funcion["arguments"] = argumentos
                    if ejecuciones >= self.max_herramientas:
                        resultado = {"error": "Límite de herramientas alcanzado; no ejecutada."}
                        limite = True
                    else:
                        ejecuciones += 1
                        self.mostrar(f"[Herramienta] {nombre}({json.dumps(argumentos, ensure_ascii=False)})")
                        resultado = ejecutar_herramienta(nombre, argumentos)
                        if nombre == "buscar_destinos" and resultado.get("destinos") == []:
                            resultado["aviso"] = (
                                "Sin coincidencias para estos filtros, no significa que no haya destinos. "
                                "Revisa los filtros usados frente a las preferencias del usuario. "
                                "No quites preferencias explícitas sin preguntar. Si no había filtros, "
                                "esta búsqueda sí cubre todo el catálogo."
                            )
                        self.mostrar(f"[Resultado] {json.dumps(resultado, ensure_ascii=False)}")
                    self.historial.append({
                        "role": "tool", "tool_name": nombre,
                        "content": json.dumps(resultado, ensure_ascii=False),
                    })
                if limite:
                    break
        except ErrorOllama:
            # Evita dejar llamadas pendientes y conserva los turnos anteriores.
            del self.historial[inicio:]
            raise
        return self._terminar(
            "He alcanzado el límite de consultas de este turno. "
            "No puedo completar la recomendación con certeza. Puedes concretar tu petición."
        )

    def _terminar(self, texto):
        self.historial.append({"role": "assistant", "content": texto})
        return texto

    def _regiones_usuario(self):
        """Solo reconoce regiones expresadas explícitamente, nunca las deduce de Madrid."""
        regiones = set()
        equivalencias = {"occidental": "oeste", "oriental": None,
                         "septentrional": "norte", "meridional": "sur", "central": "centro"}
        for mensaje in self.historial:
            if mensaje["role"] != "user" or mensaje.get("interno"):
                continue
            texto = _normalizar(mensaje["content"])
            if re.search(r"sin (?:preferencia de )?region|cualquier region|toda europa|sin restriccion de region|"
                         r"(?:me|nos) da igual (?:la )?region|(?:la )?region (?:me|nos) da igual|"
                         r"no (?:tengo|tenemos) preferencia(?:s)? (?:de |por la )?region", texto):
                regiones = set()
                continue
            explicitas = set(re.findall(r"\b(sur|oeste|centro|norte)\b", texto))
            for palabra, region in equivalencias.items():
                if region and re.search(r"europa " + palabra + r"\b", texto):
                    explicitas.add(region)
            if explicitas:
                regiones = explicitas
        return regiones

    def _intereses_usuario(self):
        """Vocabulario pequeño y explícito; 'barato' no implica ningún interés."""
        intereses = set()
        patrones = {
            "cultura": r"\bcultur(?:a|al|ales)\b",
            "gastronomia": r"\bgastronom(?:ia|ico|ica|icos|icas)\b",
            "playa": r"\bplayas?\b",
            "naturaleza": r"\bnaturaleza\b",
        }
        for mensaje in self.historial:
            if mensaje["role"] != "user" or mensaje.get("interno"):
                continue
            texto = _normalizar(mensaje["content"])
            if re.search(r"sin (?:preferencias de )?intereses|no (?:tengo|tenemos) intereses|"
                         r"(?:me|nos) dan? igual (?:los )?intereses", texto):
                intereses = set()
                continue
            # No convertir una exclusión (por ejemplo 'no queremos playa') en gusto.
            afirmativo = re.sub(r"\b(?:no|sin)\b[^.,;!?]*", "", texto)
            nuevos = {interes for interes, patron in patrones.items() if re.search(patron, afirmativo)}
            excluidos = {interes for interes, patron in patrones.items()
                         if re.search(patron, texto) and not re.search(patron, afirmativo)}
            intereses.difference_update(excluidos)
            if nuevos:
                if re.search(r"ahora|en lugar|cambi", texto):
                    intereses = nuevos
                else:
                    intereses.update(nuevos)
        return intereses

    def _ajustar_filtros_busqueda(self, argumentos):
        """Corrige filtros sin respaldo antes de ejecutar y registrar la llamada."""
        ajustados = dict(argumentos)
        region = ajustados.get("region")
        if region is not None and (
            not isinstance(region, str) or _normalizar(region) not in self._regiones_usuario()
        ):
            ajustados.pop("region", None)
            self.mostrar("[Validación] Región no indicada o indiferente; búsqueda sin región.")
        intereses = ajustados.get("intereses")
        if isinstance(intereses, list) and all(isinstance(i, str) for i in intereses):
            permitidos = self._intereses_usuario()
            conservados = [i for i in intereses if _normalizar(i) in permitidos]
            if conservados != intereses:
                self.mostrar("[Validación] Se eliminan intereses no indicados por el usuario.")
            if conservados:
                ajustados["intereses"] = conservados
            else:
                ajustados.pop("intereses", None)
        return ajustados

    def _faltan_datos_imprescindibles(self):
        """Solo orienta las preguntas; los valores siguen interpretándose en el LLM."""
        texto = _normalizar(" ".join(m["content"] for m in self.historial
                                     if m["role"] == "user" and not m.get("interno")))
        numeros = r"(?:\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)"
        mencionados = {
            "origen": re.search(r"\bdesde\s+\w+|\bsal(?:imos|go)\s+de\s+\w+", texto),
            "duración": re.search(numeros + r"\s+dias?\b", texto),
            "viajeros": re.search(r"\bsomos\s+" + numeros + r"\b|" + numeros
                                  + r"\s+(?:personas?|viajeros?)\b|con otra persona", texto),
            "presupuesto": re.search(r"\d[\d.,]*\s*(?:€|euros?\b|eur\b)", texto),
        }
        return [nombre for nombre, presente in mencionados.items() if not presente]

    def _ultima_busqueda(self):
        for indice in range(len(self.historial) - 1, -1, -1):
            mensaje = self.historial[indice]
            if mensaje["role"] == "tool" and mensaje.get("tool_name") == "buscar_destinos":
                # La llamada ya tiene los argumentos corregidos, no los inventados.
                for anterior in reversed(self.historial[:indice]):
                    for llamada in reversed(anterior.get("tool_calls", [])):
                        if llamada["function"]["name"] == "buscar_destinos":
                            return llamada["function"].get("arguments", {}), json.loads(mensaje["content"])
        return None

    def _validar_respuesta(self, mensaje):
        """Los precios se redactan en Python; el LLM solo propone IDs y contexto."""
        propuesta = mensaje.get("propuesta", {})
        if propuesta:
            return self._redactar_propuesta(propuesta)
        texto = mensaje["content"]
        destinos = _cargar_catalogo()["destinos"]
        normalizado = _normalizar(texto)
        if re.search(r"region|intereses|gustos|preferencias", normalizado) and "?" in texto:
            faltan = self._faltan_datos_imprescindibles()
            if faltan:
                return None, ("Pregunta primero solo por estos datos imprescindibles pendientes: "
                              + ", ".join(faltan) + ". Región e intereses son opcionales; "
                              "no los exijas para calcular costes.")
        if re.search(r"(?:no hay|no existen|no tenemos|no quedan|no encontre|no he encontrado|"
                     r"no se encontraron|ningun|ninguna).*(?:destinos?|opciones?|disponibles)", normalizado):
            ultima = self._ultima_busqueda()
            if ultima is None:
                return None, "No puedes concluir que no hay destinos sin consultar el catálogo."
            filtros, resultado = ultima
            if "error" in resultado or resultado.get("destinos"):
                return None, "La última búsqueda no demuestra que no haya destinos disponibles."
            if filtros.get("region") or filtros.get("intereses"):
                return None, ("La lista vacía corresponde a filtros concretos. Revisa si son necesarios. "
                              "Explica 'sin coincidencias con estos filtros', no 'sin destinos'. "
                              "Si las preferencias son explícitas, pregunta antes de quitarlas.")
        menciona_destino = any(
            re.search(r"\b" + re.escape(_normalizar(d["nombre"])) + r"\b", normalizado)
            for d in destinos
        )
        # El texto libre queda reservado a preguntas y aclaraciones, no recomendaciones.
        if (menciona_destino and not texto.strip().endswith("?")) or re.search(
            r"recomiend|cumple.*presupuesto|dentro.*presupuesto|cuesta|costaria|coste|precio", normalizado
        ):
            return None, (
                "Usa una propuesta estructurada: herramienta=ninguna, respuesta vacía y "
                "argumentos con tipo (recomendacion o coste), destinos (lista de IDs), "
                "origen, duracion_dias, viajeros y presupuesto_total. "
                "Si faltan estimaciones, solicita herramientas en lugar de escribir precios."
            )
        if re.search(r"EUR\b|euros?\b|€", texto, re.I):
            return None, "No incluyas importes en texto libre; usa la propuesta estructurada."
        return texto, None

    def _redactar_propuesta(self, propuesta):
        campos = {"tipo", "destinos", "origen", "duracion_dias", "viajeros", "presupuesto_total"}
        if not isinstance(propuesta, dict) or set(propuesta) != campos:
            return None, "La propuesta debe incluir tipo, destinos, origen, duracion_dias, viajeros y presupuesto_total."
        ids = propuesta["destinos"]
        presupuesto = propuesta["presupuesto_total"]
        if (
            propuesta["tipo"] not in ("recomendacion", "coste")
            or not isinstance(ids, list) or not 1 <= len(ids) <= 3
            or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids)
            or not isinstance(propuesta["origen"], str)
            or type(propuesta["duracion_dias"]) is not int or propuesta["duracion_dias"] < 1
            or type(propuesta["viajeros"]) is not int or propuesta["viajeros"] < 1
            or (presupuesto is not None and (type(presupuesto) not in (int, float)
                                            or not math.isfinite(presupuesto) or presupuesto <= 0))
        ):
            return None, "Los datos de la propuesta no son válidos."
        if propuesta["tipo"] == "recomendacion" and presupuesto is None:
            return None, "Aclara el presupuesto total antes de recomendar opciones que lo cumplan."
        if propuesta["tipo"] == "recomendacion":
            # El importe del usuario autoriza el presupuesto, nunca un precio.
            importes_usuario = []
            for mensaje in self.historial:
                if mensaje["role"] == "user" and not mensaje.get("interno"):
                    for valor in re.findall(r"(\d+(?:[.,]\d+)*)\s*(?:EUR\b|euros?\b|€)", mensaje["content"], re.I):
                        valor = valor.replace(".", "") if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", valor) else valor
                        valor = valor.replace(".", "").replace(",", ".") if "," in valor else valor
                        importes_usuario.append(float(valor))
            if not importes_usuario or presupuesto != importes_usuario[-1]:
                return None, "Confirma el presupuesto total en EUR con el usuario; no lo inventes ni uses uno anterior."

        # La clave incluye TODOS los parámetros: nunca usar el precio de otro viaje.
        estimaciones = {}
        for mensaje in self.historial:
            if mensaje["role"] == "tool" and mensaje.get("tool_name") == "estimar_coste":
                dato = json.loads(mensaje["content"])
                if "error" not in dato:
                    clave = (dato["destino_id"], _normalizar(dato["origen"]),
                             dato["duracion_dias"], dato["viajeros"])
                    estimaciones[clave] = dato
        catalogo = {d["id"]: d for d in _cargar_catalogo()["destinos"]}
        opciones = []
        for destino_id in ids:
            clave = (destino_id, _normalizar(propuesta["origen"]),
                     propuesta["duracion_dias"], propuesta["viajeros"])
            if destino_id not in catalogo:
                return None, f"El ID {destino_id} no existe en el catálogo."
            if clave not in estimaciones:
                ejemplo = {
                    "herramienta": "estimar_coste",
                    "argumentos": {
                        "destino_id": destino_id, "origen": propuesta["origen"],
                        "duracion_dias": propuesta["duracion_dias"], "viajeros": propuesta["viajeros"],
                    },
                    "respuesta": "",
                }
                return None, (
                    f"Falta estimar_coste para {destino_id} con los parámetros actuales. "
                    "Puedes solicitar esa consulta con este formato: "
                    + json.dumps(ejemplo, ensure_ascii=False)
                    + " También puedes consultar otra opción o pedir una aclaración."
                )
            dato = estimaciones[clave]
            if propuesta["tipo"] == "recomendacion" and dato["total_grupo"] > presupuesto:
                return None, f"{destino_id} supera el presupuesto; consulta otra opción o explica la limitación."
            opciones.append((catalogo[destino_id], dato))

        encabezado = "Destinos con coste comprobado:" if propuesta["tipo"] == "recomendacion" else "Costes comprobados:"
        lineas = [encabezado]
        for destino, dato in opciones:
            lineas.append(f"- {destino['nombre']} ({destino['pais']}): {dato['total_grupo']:g} EUR "
                          f"en total; {dato['total_por_persona']:g} EUR por persona.")
            if propuesta["tipo"] == "recomendacion":
                lineas.append(f"  Dentro del presupuesto total indicado de {presupuesto:g} EUR.")
        lineas.append(f"Viaje desde {propuesta['origen']}: {propuesta['duracion_dias']} días, "
                      f"{propuesta['viajeros']} viajeros. Incluye transporte de ida y vuelta, "
                      "alojamiento y gastos diarios. Datos ficticios, no ofertas reales.")
        return "\n".join(lineas), None
