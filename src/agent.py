"""Bucle explícito con Ollama local, sin SDK ni dependencias externas."""

import copy
import inspect
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.prompts import INSTRUCCIONES
from src.presentacion import presentar_opciones
from src.datos_viaje import AgenteDatos, AgentePreferencias
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
            origen_confirmado = mensaje.pop("origen_confirmado", None)
            if origen_confirmado and mensaje.get("role") == "user":
                mensaje["content"] += f"\nConfirmo que salimos desde {origen_confirmado}."
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
    def __init__(self, cliente=None, mostrar=print, max_consultas=12, max_herramientas=10, datos=None):
        if type(max_consultas) is not int or max_consultas < 1:
            raise ValueError("max_consultas debe ser un entero positivo.")
        if type(max_herramientas) is not int or max_herramientas < 1:
            raise ValueError("max_herramientas debe ser un entero positivo.")
        self.cliente = cliente if cliente is not None else ClienteOllama()
        self.mostrar = mostrar
        self.agente_datos = AgenteDatos(datos) if datos is not None else None
        self.agente_preferencias = (
            AgentePreferencias(datos, _cargar_catalogo()["destinos"]) if datos is not None else None
        )
        self.max_consultas = max_consultas
        self.max_herramientas = max_herramientas
        self._origen_pendiente = None
        self.historial = [{"role": "system", "content": INSTRUCCIONES
                          + f"\nLímites: {max_consultas} consultas al modelo y "
                          + f"{max_herramientas} intentos de herramientas por turno."}]

    def responder(self, texto):
        if not isinstance(texto, str) or not texto.strip():
            raise ValueError("Escribe una petición no vacía.")
        inicio = len(self.historial)
        pendiente_anterior = self._origen_pendiente
        mensaje_usuario = {"role": "user", "content": texto}
        afirmacion = " ".join(re.sub(r"[^\w\s]", "", _normalizar(texto)).split())
        # En una respuesta como «León 1000€», el importe no forma parte
        # del nombre de la ciudad. Se conserva el mensaje completo en el historial.
        ciudad_respuesta = re.sub(
            r"\b\d+(?:[.,]\d+)*\s*(?:€|euros?\b|EUR\b)", "", texto, flags=re.I,
        ).strip(" ,.;")
        if self._origen_pendiente and afirmacion in ("si", "si por favor", "vale", "de acuerdo"):
            # Solo resuelve la pregunta concreta del programa; no un sí aislado.
            mensaje_usuario["origen_confirmado"] = self._origen_pendiente
        elif (self.historial[-1]["role"] == "assistant"
              and "origen" in _normalizar(self.historial[-1]["content"])
              and "?" in self.historial[-1]["content"]
              and re.fullmatch(r"[^\W\d_]+", ciudad_respuesta, re.UNICODE)
              and _normalizar(ciudad_respuesta) not in ("si", "no", "vale", "hola", "gracias", "depende", "origen")):
            # Una ciudad sola responde a la pregunta pendiente sobre origen.
            # No se deduce un origen de palabras sueltas fuera de ese contexto.
            mensaje_usuario["origen_confirmado"] = ciudad_respuesta
        self._origen_pendiente = None
        self.historial.append(mensaje_usuario)
        origen = self._origen_usuario()
        origenes = {
            _normalizar(ciudad)
            for destino in _cargar_catalogo()["destinos"]
            for ciudad in destino["costes"]["transporte_ida_vuelta_por_persona"]
        }
        if origen and _normalizar(origen) not in origenes:
            self._origen_pendiente = "Madrid"
            return self._terminar(
                f"Has indicado {origen} como origen. El catálogo actual solo permite estimar "
                "el transporte desde Madrid, así que no puedo calcular el coste total desde "
                f"{origen}. No cambiaré tu origen automáticamente. "
                "¿Quieres usar Madrid para esta demostración? Puedes responder «sí» o «desde Madrid»; "
                "si mantienes el origen actual, no disponemos de esos costes. "
                "Conservo los demás datos del viaje."
            )
        menciones = [mencion for mensaje in self.historial
                     if mensaje["role"] == "user" and not mensaje.get("interno")
                     for mencion in self._menciones_presupuesto(mensaje["content"])]
        if menciones and not menciones[-1][1]:
            # La aclaración es del programa: no es un precio ni una decisión del LLM.
            return self._terminar(
                f"¿Te refieres a {menciones[-1][0]} EUR de presupuesto total para todos los viajeros? "
                "Confirma el importe y la moneda, por ejemplo: «1400 EUR en total»."
            )
        if mensaje_usuario.get("origen_confirmado"):
            faltan = self._faltan_datos_imprescindibles()
            if faltan:
                return self._terminar(
                    "De acuerdo, usaremos Madrid como origen. Para continuar, faltan: "
                    + ", ".join(faltan) + ". ¿Puedes indicarlos? "
                    "Conservo los demás datos del viaje."
                )
        ejecuciones = 0
        objetivo = self._cantidad_solicitada()
        parcial = None
        errores_seguidos = 0
        try:
            for consulta in range(self.max_consultas):
                mensaje = copy.deepcopy(self.cliente.chat(self.historial))
                self.historial.append(mensaje)
                llamadas = mensaje.get("tool_calls", [])
                if not llamadas:
                    if mensaje.get("content", "").strip() or mensaje.get("propuesta"):
                        # Qwen3 puede copiar un saludo anterior aunque el usuario
                        # haya aportado datos. No gastar otro ciclo en corregirlo.
                        texto_respuesta = mensaje.get("content", "")
                        repetida = any(
                            anterior["role"] == "assistant"
                            and " ".join(_normalizar(anterior.get("content", "")).split())
                            == " ".join(_normalizar(texto_respuesta).split())
                            for anterior in self.historial[:-1]
                        )
                        faltan = self._faltan_datos_imprescindibles()
                        if not mensaje.get("propuesta") and repetida and "?" in texto_respuesta and faltan:
                            mensaje["content"] = (
                                "Para continuar con el viaje que indicas, faltan estos datos: "
                                + ", ".join(faltan) + ". ¿Puedes indicarlos? "
                                "Conservo la información que ya has dado."
                            )
                            return mensaje["content"]
                        respuesta, error = self._validar_respuesta(mensaje)
                        if not error and objetivo > 1 and mensaje.get("propuesta", {}).get("tipo") == "recomendacion":
                            ampliada = self._completar_multiple(mensaje["propuesta"], objetivo)
                            if not ampliada["destinos"]:
                                error = "No hay costes verificados compatibles con las preferencias; consulta otras opciones."
                            else:
                                respuesta, error = self._redactar_propuesta(ampliada)
                                if not error:
                                    parcial = ampliada
                                    pendientes = self._pendientes_multiple(ampliada)
                                    if (len(ampliada["destinos"]) < objetivo and pendientes
                                            and consulta + 1 < self.max_consultas
                                            and ejecuciones < self.max_herramientas):
                                        error = (
                                            f"El usuario pidió {objetivo} opciones y solo hay "
                                            f"{len(ampliada['destinos'])} con coste verificado. Intenta completar la comparación. "
                                            f"IDs compatibles aún sin coste comprobado: {', '.join(pendientes)}. "
                                            "Elige qué consultar con estimar_coste; no repitas los costes ya disponibles."
                                        )
                                    else:
                                        mensaje["propuesta"] = ampliada
                                        respuesta += self._nota_cantidad(ampliada, objetivo)
                        if error:
                            # No conservar una recomendación inventada como si fuera válida.
                            self.historial.pop()
                            errores_seguidos += 1
                            hay_costes = any(
                                m["role"] == "tool" and m.get("tool_name") == "estimar_coste"
                                and "error" not in json.loads(m["content"])
                                for m in self.historial[inicio:]
                            )
                            if errores_seguidos >= 2 and faltan and not hay_costes:
                                # No dejar que una aclaración inicial consuma el turno.
                                return self._terminar(
                                    "Para continuar, necesito estos datos: " + ", ".join(faltan)
                                    + ". ¿Puedes indicarlos? El presupuesto debe ser el total del grupo, "
                                    "con su moneda. Conservo los datos que ya has dado."
                                )
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
                errores_seguidos = 0
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
                        resultado = self._coste_descartado(argumentos) if nombre == "estimar_coste" else None
                        if resultado is None:
                            resultado = ejecutar_herramienta(nombre, argumentos)
                        if self.agente_datos and "error" not in resultado:
                            if nombre == "buscar_destinos":
                                candidatos, perfil = self.agente_preferencias.priorizar(resultado["destinos"])
                                if perfil:
                                    resultado["perfil_aprendido"] = perfil
                                    self.mostrar("[Agente de preferencias] Orden de candidatos: "
                                                 + ", ".join(d["nombre"] for d in candidatos))
                                resultado["destinos"] = [self.agente_datos.enriquecer(d) for d in candidatos]
                            elif nombre == "consultar_destino":
                                resultado = self.agente_datos.enriquecer(resultado)
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
                    if nombre == "estimar_coste" and "error" not in resultado:
                        # Solo reúne costes solicitados por el LLM. No ejecuta nuevas
                        # consultas ni calcula precios directamente desde el catálogo.
                        contexto = {
                            "tipo": "recomendacion", "destinos": [],
                            "origen": resultado["origen"], "duracion_dias": resultado["duracion_dias"],
                            "viajeros": resultado["viajeros"], "presupuesto_total": self._presupuesto_usuario(),
                        }
                        presupuesto = contexto["presupuesto_total"]
                        if presupuesto is not None and math.isfinite(presupuesto) and presupuesto > 0:
                            # Conservar el viaje aunque todos los costes excedan el presupuesto.
                            parcial = contexto
                            if resultado["total_grupo"] > presupuesto:
                                self.historial.append({
                                    "role": "user", "interno": True,
                                    "content": (
                                        f"Descartado por presupuesto para este viaje: {resultado['destino_id']} "
                                        f"({resultado['total_grupo']:g} EUR frente a {presupuesto:g} EUR). "
                                        "No vuelvas a proponerlo ni a estimarlo con los mismos datos. "
                                        "Elige otro candidato sin coste verificado o pide una aclaración."
                                    ),
                                })

                if limite:
                    break
        except ErrorOllama:
            # Evita dejar llamadas pendientes y conserva los turnos anteriores.
            del self.historial[inicio:]
            self._origen_pendiente = pendiente_anterior
            raise
        if parcial is not None:
            respuesta = self._respuesta_al_limite(parcial, objetivo)
            if respuesta is not None:
                return self._terminar(respuesta)
        return self._terminar(
            "He alcanzado el límite de consultas de este turno. "
            "No puedo completar la recomendación con certeza. Puedes concretar tu petición."
        )

    def _terminar(self, texto):
        self.historial.append({"role": "assistant", "content": texto})
        return texto

    def _coste_descartado(self, argumentos):
        """Reutiliza solo un coste descartado del mismo viaje y presupuesto actual.

        El intento sigue contando para el límite. Un cambio de presupuesto u
        otros parámetros permite volver a considerar el destino.
        """
        campos = {"destino_id", "origen", "duracion_dias", "viajeros"}
        if not isinstance(argumentos, dict) or set(argumentos) != campos:
            return None
        if (not isinstance(argumentos["destino_id"], str)
                or not isinstance(argumentos["origen"], str)
                or type(argumentos["duracion_dias"]) is not int or argumentos["duracion_dias"] < 1
                or type(argumentos["viajeros"]) is not int or argumentos["viajeros"] < 1):
            return None
        presupuesto = self._presupuesto_usuario()
        if presupuesto is None:
            return None
        dato = self._costes_multiple(argumentos).get(_normalizar(argumentos["destino_id"]))
        if dato is not None and dato["total_grupo"] > presupuesto:
            return {**dato, "aviso": "Coste ya comprobado y descartado para este presupuesto; no se ha recalculado."}
        return None

    def _respuesta_al_limite(self, contexto, objetivo):
        """Cierre determinista: ninguna frase ni importe procede de prosa del LLM."""
        propuesta = self._completar_multiple(contexto, objetivo)
        if propuesta["destinos"]:
            respuesta, error = self._redactar_propuesta(propuesta)
            return respuesta + self._nota_cantidad(propuesta, objetivo) if not error else None

        # Si no hay opciones viables, mostrar únicamente costes exitosos del
        # mismo viaje y candidatos que respetan los filtros reales del usuario.
        catalogo = {d["id"]: d for d in _cargar_catalogo()["destinos"]}
        candidatos = self._candidatos_multiple()
        costes = self._costes_multiple(contexto)
        comprobados = [(catalogo[i], dato) for i, dato in costes.items() if i in candidatos]
        if not comprobados:
            return None
        respuesta = presentar_opciones(
            comprobados, contexto["presupuesto_total"], self._intereses_usuario(), "descartados"
        )
        pendientes = self._pendientes_multiple(contexto)
        if pendientes:
            sin_verificar = ("Queda 1 candidato compatible sin verificar. " if len(pendientes) == 1
                             else f"Quedan {len(pendientes)} candidatos compatibles sin verificar. ")
            alcance = (sin_verificar
                       + "Esto no demuestra que no existan destinos válidos en todo el catálogo.")
        else:
            alcance = ("Se ha comprobado el coste de todos los candidatos compatibles con tus preferencias; "
                       "ninguno cumple el presupuesto indicado.")
        return (respuesta + "\n\nHe alcanzado el límite de consultas de este turno. "
                "Los destinos comprobados superan el presupuesto; no se recomiendan. "
                + alcance + " Puedes pedir continuar la búsqueda o revisar el presupuesto, sin cambiarlo automáticamente.")

    def _cantidad_solicitada(self):
        """Reconoce cantidades junto a opciones, nunca el número de viajeros/días."""
        cantidad = 1
        numeros = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3}
        patron = (r"\b(?:hasta\s+)?(un|uno|una|dos|tres|[1-9]\d*)\s+"
                  r"(?:destinos?|opciones?|recomendaciones?|alternativas?)\b|"
                  r"\b(?:varios|varias|diferentes|distintos|distintas|mas)\s+"
                  r"(?:destinos|opciones|recomendaciones|alternativas)\b")
        for mensaje in self.historial:
            if mensaje["role"] != "user" or mensaje.get("interno"):
                continue
            texto = _normalizar(mensaje["content"])
            coincidencias = list(re.finditer(patron, texto))
            if coincidencias:
                valor = coincidencias[-1].group(1)
                cantidad = min(3, int(valor) if valor and valor.isdigit() else numeros.get(valor, 3))
            elif re.search(r"\b(?:cuanto|coste|precio)\b", texto):
                # Una pregunta posterior de precio no obliga a buscar alternativas.
                cantidad = 1
        return cantidad

    def _candidatos_multiple(self):
        """Solo valida compatibilidad con los filtros reales; no consulta precios."""
        regiones = self._regiones_usuario()
        intereses = self._intereses_usuario()
        return {
            d["id"] for d in _cargar_catalogo()["destinos"]
            if (not regiones or d["region"] in regiones)
            and intereses.issubset(d["intereses"])
        }

    def _costes_multiple(self, propuesta):
        costes = {}
        for mensaje in self.historial:
            if mensaje["role"] != "tool" or mensaje.get("tool_name") != "estimar_coste":
                continue
            dato = json.loads(mensaje["content"])
            if ("error" not in dato
                    and _normalizar(dato["origen"]) == _normalizar(propuesta["origen"])
                    and dato["duracion_dias"] == propuesta["duracion_dias"]
                    and dato["viajeros"] == propuesta["viajeros"]):
                costes[dato["destino_id"]] = dato
        return costes

    def _completar_multiple(self, propuesta, objetivo):
        """Incluye hasta el objetivo entre los destinos que el LLM ha evaluado."""
        candidatos = self._candidatos_multiple()
        costes = self._costes_multiple(propuesta)
        validos = [dato for destino, dato in costes.items()
                   if destino in candidatos and dato["total_grupo"] <= propuesta["presupuesto_total"]]
        validos.sort(key=lambda dato: dato["total_grupo"])
        return {**propuesta, "destinos": [d["destino_id"] for d in validos[:objetivo]]}

    def _pendientes_multiple(self, propuesta):
        return sorted(self._candidatos_multiple() - self._costes_multiple(propuesta).keys())

    def _nota_cantidad(self, propuesta, objetivo):
        encontrados = len(propuesta["destinos"])
        if encontrados >= objetivo:
            return ""
        if self._pendientes_multiple(propuesta):
            verbo = "Se muestra" if encontrados == 1 else "Se muestran"
            return (f"\n\n{verbo} {encontrados} de las {objetivo} opciones solicitadas: "
                    "se alcanzó el límite de búsqueda. Quedan candidatos sin comprobar; "
                    "no significa que no existan otras opciones válidas.")
        disponibles = "1 opción válida" if encontrados == 1 else f"{encontrados} opciones válidas"
        return (f"\n\nSolo hay {disponibles} de las {objetivo} solicitadas "
                "tras comprobar el coste de todos los destinos compatibles con tus filtros.")

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

    def _origen_usuario(self):
        """Reconoce las formas de origen usadas en esta demostración.

        Solo las ciudades de una palabra tienen datos en el catálogo actual.
        No toma una ciudad mencionada por el modelo como origen confirmado.
        """
        origen = None
        for mensaje in self.historial:
            if mensaje["role"] == "user" and not mensaje.get("interno"):
                coincidencias = re.findall(
                    r"\b(?:desde|salimos\s+de|salgo\s+de)\s+([\wáéíóúüñ]+)",
                    mensaje["content"], re.I,
                )
                if coincidencias:
                    origen = coincidencias[-1]
                elif mensaje.get("origen_confirmado"):
                    origen = mensaje["origen_confirmado"]
        return origen

    def _faltan_datos_imprescindibles(self):
        """Solo orienta las preguntas; los valores siguen interpretándose en el LLM."""
        texto = _normalizar(" ".join(m["content"] for m in self.historial
                                     if m["role"] == "user" and not m.get("interno")))
        numeros = r"(?:\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)"
        mencionados = {
            "origen": self._origen_usuario() is not None,
            "duración": re.search(numeros + r"\s+(?:dias?|semanas?)\b", texto),
            "viajeros": re.search(r"\bsomos\s+" + numeros + r"\b|" + numeros
                                  + r"\s+(?:personas?|viajeros?)\b|con otra persona", texto),
            "presupuesto": self._presupuesto_usuario() is not None,
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
        # Nombrar la moneda en una pregunta no equivale a inventar un precio.
        pregunta_moneda = "?" in texto and not re.search(r"\d", texto) and not menciona_destino
        if re.search(r"EUR\b|euros?\b|€", texto, re.I) and not pregunta_moneda:
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
        presupuesto_usuario = self._presupuesto_usuario()
        if presupuesto is not None and presupuesto != presupuesto_usuario:
            return None, "Confirma el presupuesto total en EUR con el usuario; no lo inventes ni uses uno anterior."
        # Una consulta de costes puede no incluir presupuesto en la propuesta,
        # pero se muestra el ya indicado en la conversación, si existe.
        presupuesto = presupuesto_usuario

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
                return None, (f"{destino_id} supera el presupuesto y está descartado para este viaje. "
                              "No vuelvas a proponerlo con los mismos datos; consulta otra opción "
                              "o explica la limitación.")
            opciones.append((catalogo[destino_id], dato))

        respuesta = presentar_opciones(
            opciones, presupuesto, self._intereses_usuario(), propuesta["tipo"]
        )
        if self.agente_datos and propuesta["tipo"] == "recomendacion":
            lugares = [self.agente_datos.datos.lugar(destino["id"]) for destino, _ in opciones]
            enlaces = [f"- [{lugar['nombre']}]({lugar['url']}) · {lugar['fuente']}"
                       for lugar in lugares if lugar]
            if enlaces:
                respuesta += "\n\nLugares documentados:\n" + "\n".join(enlaces)
        return respuesta, None

    @staticmethod
    def _menciones_presupuesto(texto):
        """Detecta importes explícitos o un posible presupuesto sin moneda.

        No interpreta números sueltos ni cantidades de días o viajeros.
        Un importe sin moneda se conserva como pendiente, nunca como confirmado.
        """
        numero = r"\d+(?:[.,]\d+)*"
        patron = (
            rf"(?P<explicito>{numero})\s*(?:EUR\b|euros?\b|€)"
            rf"|(?:\btenemos|\bdispongo\s+de|\bdisponemos\s+de|"
            rf"\bpresupuesto(?:\s+total|\s+maximo)?(?:\s+es)?(?:\s+de)?)"
            rf"\s*[:=]?\s*(?P<pendiente>{numero})(?!\d|[.,]\d)"
            rf"(?!\s*(?:personas?|viajeros?|dias?|noches?|destinos?|opciones?)\b)"
        )
        menciones = []
        for coincidencia in re.finditer(patron, _normalizar(texto), re.I):
            valor = coincidencia.group("explicito") or coincidencia.group("pendiente")
            # El segundo caso puede consumir también una cantidad con moneda.
            resto = _normalizar(texto)[coincidencia.end():]
            confirmado = bool(coincidencia.group("explicito") or
                              re.match(r"\s*(?:eur\b|euros?\b|€)", resto))
            menciones.append((valor, confirmado))
        return menciones

    def _presupuesto_usuario(self):
        """La última mención sustituye a la anterior, incluso si falta confirmar."""
        ultimo = None
        for mensaje in self.historial:
            if mensaje["role"] == "user" and not mensaje.get("interno"):
                for valor, confirmado in self._menciones_presupuesto(mensaje["content"]):
                    valor = valor.replace(".", "") if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", valor) else valor
                    valor = valor.replace(".", "").replace(",", ".") if "," in valor else valor
                    ultimo = float(valor) if confirmado else None
        return ultimo
