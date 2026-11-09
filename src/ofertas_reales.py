"""Consultas de ida y vuelta y alojamiento mediante SerpApi."""

from datetime import datetime
import json
from math import isfinite
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


class ErrorOfertas(Exception):
    """Mensaje seguro para mostrar en la interfaz."""


class ErrorConsultaOfertas(ErrorOfertas):
    """SerpApi no pudo comprobar una consulta concreta."""


def consultar_serpapi(clave, parametros):
    url = "https://serpapi.com/search.json?" + urlencode({**parametros, "api_key": clave})
    try:
        with urlopen(url, timeout=25) as respuesta:
            datos = json.load(respuesta)
    except HTTPError as error:
        if error.code in (401, 403):
            raise ErrorOfertas("SerpApi rechazó el acceso. Revisa que la clave sea válida y esté activa.") from None
        if error.code == 429:
            raise ErrorOfertas("SerpApi alcanzó el límite de búsquedas. Revisa la cuota en tu cuenta.") from None
        if error.code in (400, 422):
            raise ErrorConsultaOfertas(f"SerpApi rechazó esta consulta (HTTP {error.code}).") from None
        raise ErrorOfertas("SerpApi no pudo completar la consulta.") from None
    except (URLError, TimeoutError, ValueError):
        raise ErrorOfertas("No se pudo leer la respuesta de SerpApi. Inténtalo de nuevo.") from None
    if not isinstance(datos, dict):
        raise ErrorOfertas("SerpApi devolvió una respuesta inesperada.")
    estado = (datos.get("search_metadata") or {}).get("status")
    if datos.get("error") and estado == "Success":
        # SerpApi usa este estado con un mensaje de error cuando no hay resultados.
        return {}
    if datos.get("error") or estado == "Error":
        raise ErrorConsultaOfertas("SerpApi no pudo verificar esta consulta.")
    return datos


def opciones_vuelo(datos):
    return [*datos.get("best_flights", []), *datos.get("other_flights", [])]


def importe_valido(valor):
    return type(valor) in (int, float) and isfinite(valor) and valor > 0


def hora_segmento(segmentos, aeropuerto):
    segmento = segmentos[-1] if aeropuerto == "arrival_airport" else segmentos[0]
    try:
        return datetime.fromisoformat(segmento[aeropuerto]["time"])
    except (KeyError, TypeError, ValueError):
        return None


def buscar_planes(consultar, origen, destino, ciudad, ida, vuelta, adultos, presupuesto):
    """Combina resultados del proveedor sin completar precios o tramos ausentes."""
    comunes = {"currency": "EUR", "adults": adultos, "hl": "es", "gl": "es"}
    ruta = {
        **comunes, "engine": "google_flights", "type": 1, "departure_id": origen,
        "arrival_id": destino, "outbound_date": ida.isoformat(), "return_date": vuelta.isoformat(),
        "sort_by": 2,
    }
    vuelos = []
    tokens = set()
    registro = []
    for opcion in opciones_vuelo(consultar(ruta)):
        tramos_ida = opcion.get("flights") or []
        token = opcion.get("departure_token")
        if not tramos_ida or not token or token in tokens:
            continue
        llegada = hora_segmento(tramos_ida, "arrival_airport")
        if not llegada or llegada.date() != ida:
            continue
        tokens.add(token)
        try:
            regresos = consultar({**ruta, "departure_token": token})
        except ErrorConsultaOfertas:
            regresos = {}
            registro.append("SerpApi no pudo verificar la vuelta de una de las opciones de ida.")
        for regreso in opciones_vuelo(regresos):
            tramos_vuelta = regreso.get("flights") or []
            precio = regreso.get("price")
            if tramos_vuelta and importe_valido(precio):
                vuelos.append((precio, tramos_ida, tramos_vuelta))
        if len(tokens) == 2:
            break
    if not vuelos:
        return [], [*registro, "Google Flights no devolvió una ida y vuelta utilizable entre las opciones consultadas."]

    hoteles = consultar({
        **comunes, "engine": "google_hotels", "q": ciudad,
        "check_in_date": ida.isoformat(), "check_out_date": vuelta.isoformat(),
    })
    alojamientos = []
    for hotel in hoteles.get("properties", []):
        tarifa = hotel.get("total_rate") or {}
        precio = tarifa.get("extracted_after_taxes_fees")
        impuestos = importe_valido(precio)
        if not impuestos:
            precio = tarifa.get("extracted_display_price")
        if hotel.get("name") and importe_valido(precio):
            alojamientos.append((precio, hotel["name"], impuestos))
    planes = [
        {"total": precio_vuelo + precio_hotel, "vuelo": precio_vuelo, "alojamiento": precio_hotel,
         "nombre": nombre, "ida": tramos_ida, "vuelta": tramos_vuelta, "impuestos_confirmados": impuestos}
        for precio_vuelo, tramos_ida, tramos_vuelta in vuelos
        for precio_hotel, nombre, impuestos in alojamientos
    ]
    planes.sort(key=lambda plan: (not plan["impuestos_confirmados"], plan["total"]))
    registro.extend([
        f"Transporte: {len(vuelos)} idas y vueltas con precio, tras revisar {len(tokens)} opciones de ida.",
        f"Alojamiento: {sum(impuestos for _, _, impuestos in alojamientos)} tarifas con impuestos y "
        f"{sum(not impuestos for _, _, impuestos in alojamientos)} con impuestos por confirmar.",
        f"Coordinación: {sum(plan['impuestos_confirmados'] and plan['total'] > presupuesto for plan in planes)} combinaciones superan el presupuesto.",
    ])
    return planes[:3], registro
