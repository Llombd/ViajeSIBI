"""Tres herramientas locales. No contienen llamadas a un LLM ni a internet."""

import json
import unicodedata
from pathlib import Path


CATALOGO = Path(__file__).resolve().parent.parent / "data" / "destinos.json"


def _normalizar(texto):
    """Permite comparar Madrid/madrid o gastronomía/gastronomia."""
    texto = unicodedata.normalize("NFD", texto.strip().casefold())
    return "".join(letra for letra in texto if not unicodedata.combining(letra))


def _cargar_catalogo():
    with CATALOGO.open(encoding="utf-8") as archivo:
        return json.load(archivo)


def _obtener_destino(destino_id):
    if not isinstance(destino_id, str):
        return None
    for destino in _cargar_catalogo()["destinos"]:
        if destino["id"] == _normalizar(destino_id):
            return destino
    return None


def _entero_positivo(valor):
    # bool es una subclase de int, pero True no es una duración válida.
    return type(valor) is int and valor > 0


def buscar_destinos(region=None, intereses=None):
    """Filtra por región y por TODOS los intereses solicitados.

    Regiones: sur, oeste, centro y norte. Sin filtros devuelve el catálogo.
    Los intereses se pasan como una lista de textos, por ejemplo ["cultura"].
    """
    if region is not None and not isinstance(region, str):
        return {"error": "La región debe ser un texto."}
    if intereses is not None and (
        not isinstance(intereses, list)
        or any(not isinstance(interes, str) for interes in intereses)
    ):
        return {"error": "Los intereses deben ser una lista de textos."}

    solicitados = {_normalizar(interes) for interes in (intereses or [])}
    resultados = []
    for destino in _cargar_catalogo()["destinos"]:
        if region is not None and _normalizar(region) != destino["region"]:
            continue
        if not solicitados.issubset(set(destino["intereses"])):
            continue
        resultados.append({
            clave: destino[clave]
            for clave in ("id", "nombre", "pais", "region", "intereses")
        })
    return {"tipo_datos": "ficticios", "destinos": resultados}


def consultar_destino(destino_id, mes):
    """Devuelve los detalles y el clima ficticio del mes (entero de 1 a 12)."""
    if type(mes) is not int or not 1 <= mes <= 12:
        return {"error": "El mes debe ser un entero entre 1 y 12."}
    destino = _obtener_destino(destino_id)
    if destino is None:
        return {"error": "El destino no existe en el catálogo."}

    clima = destino["clima_mensual"].get(str(mes))
    if clima is None:
        return {"error": "No hay datos de clima para ese mes."}
    return {
        "tipo_datos": "ficticios",
        "id": destino["id"],
        "nombre": destino["nombre"],
        "pais": destino["pais"],
        "region": destino["region"],
        "intereses": destino["intereses"],
        "actividades": destino["actividades"],
        "mes": mes,
        "clima": clima,
    }


def estimar_coste(destino_id, origen, duracion_dias, viajeros):
    """Estima el coste total en EUR para todo el grupo.

    Se cuentan duración - 1 noches. Los datos de transporte solo incluyen
    Madrid como origen. No se inventan rutas para otras ciudades.
    """
    if not _entero_positivo(duracion_dias) or not _entero_positivo(viajeros):
        return {"error": "La duración y los viajeros deben ser enteros positivos."}
    if not isinstance(origen, str) or not origen.strip():
        return {"error": "El origen debe ser un texto no vacío."}
    destino = _obtener_destino(destino_id)
    if destino is None:
        return {"error": "El destino no existe en el catálogo."}

    costes = destino["costes"]
    rutas = costes["transporte_ida_vuelta_por_persona"]
    origen_catalogo = next(
        (ciudad for ciudad in rutas if _normalizar(ciudad) == _normalizar(origen)),
        None,
    )
    if origen_catalogo is None:
        return {"error": "No hay datos de transporte desde ese origen."}

    noches = duracion_dias - 1
    transporte = rutas[origen_catalogo] * viajeros
    alojamiento = costes["alojamiento_por_persona_noche"] * noches * viajeros
    gastos = costes["gastos_por_persona_dia"] * duracion_dias * viajeros
    total = transporte + alojamiento + gastos
    return {
        "tipo_datos": "ficticios",
        "moneda": "EUR",
        "destino_id": destino["id"],
        "origen": origen_catalogo,
        "duracion_dias": duracion_dias,
        "noches": noches,
        "viajeros": viajeros,
        "desglose": {
            "transporte": transporte,
            "alojamiento": alojamiento,
            "gastos_diarios": gastos,
        },
        "total_grupo": total,
        "total_por_persona": round(total / viajeros, 2),
        "supuestos": [
            "Transporte de ida y vuelta por persona.",
            "Alojamiento por persona y noche; no se calcula por habitación.",
            "Una noche menos que días de viaje.",
            "Gastos diarios por persona.",
            "Sin ajuste por fechas, disponibilidad ni temporada.",
            "Datos ficticios: no son ofertas ni precios reales.",
        ],
    }
