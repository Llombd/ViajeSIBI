"""Consultas de ida y vuelta y alojamiento mediante SerpApi."""

from datetime import datetime
import json
from math import isfinite
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen


TIPOS_ALOJAMIENTO = {
    "Hoteles de playa": 12, "Hoteles boutique": 13, "Hostales y albergues": 14,
    "Posadas": 15, "Moteles": 16, "Resorts": 17, "Hoteles con spa": 18,
    "Bed & breakfast": 19, "Otros": 20, "Apartahoteles": 21,
    "Minshuku": 22, "Hoteles de negocios japoneses": 23, "Ryokan": 24,
}


def consultar_con_filtros(consultar, parametros, tipos, nota_minima):
    if parametros["engine"] != "google_hotels":
        return consultar(parametros)
    if tipos is not None:
        parametros = {**parametros, "property_types": ",".join(str(codigo) for codigo in tipos)}
    datos = consultar(parametros)
    if nota_minima:
        datos = {**datos, "properties": [
            hotel for hotel in datos.get("properties", [])
            if importe_valido(hotel.get("overall_rating")) and nota_minima <= hotel["overall_rating"] <= 5
        ]}
    return datos


def enlace_vuelos(datos):
    url = (datos.get("search_metadata") or {}).get("google_flights_url")
    if isinstance(url, str):
        enlace = urlsplit(url)
        if (enlace.scheme == "https" and enlace.netloc == "www.google.com"
                and enlace.path == "/travel/flights" and parse_qs(enlace.query).get("tfs")):
            return url
    return None


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


def buscar_planes(consultar, origen, destino, ciudad, ida, vuelta, adultos, presupuesto, *, diagnostico=None, limite_total=None):
    """Combina resultados del proveedor sin completar precios o tramos ausentes."""
    # Conserva también los resultados parciales: sin hotel puede haber un vuelo útil.
    if diagnostico is None:
        diagnostico = {}
    diagnostico.update(estado="sin_vuelos", vuelos=0, alojamientos=0)
    comunes = {"currency": "EUR", "adults": adultos, "hl": "es", "gl": "es"}
    ruta = {
        **comunes, "engine": "google_flights", "type": 1, "departure_id": origen,
        "arrival_id": destino, "outbound_date": ida.isoformat(), "return_date": vuelta.isoformat(),
        "sort_by": 2,
    }
    vuelos, registro = consultar_vuelos(consultar, ruta, ida)
    if not vuelos:
        return [], [*registro, "Google Flights no devolvió una ida y vuelta utilizable entre las opciones consultadas."]

    diagnostico.update(estado="sin_alojamiento", vuelos=len(vuelos),
                       vuelo_minimo=min(vuelo[0] for vuelo in vuelos))

    # Una estancia no puede abaratar un vuelo que ya supera todo el máximo.
    # Solo descartamos las combinaciones de vuelos consultadas, no toda la ruta.
    if limite_total is not None and diagnostico["vuelo_minimo"] > limite_total:
        diagnostico.update(estado="vuelo_supera_maximo", limite_total=limite_total,
                           consultas_hotel_evitadas=1)
        registro.append(
            f"Los vuelos comprobados cuestan al menos {diagnostico['vuelo_minimo']:.2f} €, "
            f"más que el máximo de {limite_total:.2f} €. Python evita consultar el hotel; "
            "estas combinaciones no pueden encajar. Quedan otras rutas o fechas por comprobar."
        )
        return [], registro

    hoteles = consultar({
        **comunes, "engine": "google_hotels", "q": ciudad,
        "check_in_date": ida.isoformat(), "check_out_date": vuelta.isoformat(),
    })
    alojamientos = extraer_alojamientos(hoteles)
    planes = combinar_ofertas(vuelos, alojamientos)
    diagnostico["alojamientos"] = len(alojamientos)
    if alojamientos:
        diagnostico.update(estado="con_ofertas", alojamiento_minimo=min(hotel[0] for hotel in alojamientos))
    registro.extend([
        f"Transporte: {len(vuelos)} idas y vueltas con precio, entre las opciones de ida consultadas.",
        f"Alojamiento: {sum(impuestos for _, _, impuestos, _ in alojamientos)} tarifas con impuestos y "
        f"{sum(not impuestos for _, _, impuestos, _ in alojamientos)} con impuestos por confirmar.",
        f"Coordinación: {sum(plan['total'] > presupuesto for plan in planes)} combinaciones superan el presupuesto según la tarifa publicada.",
    ])
    return planes[:3], registro



def consultar_vuelos(consultar, ruta, ida, elegir=None):
    vuelos = []
    tokens = set()
    registro = []
    ida_resultados = consultar(ruta)
    enlace_ida = enlace_vuelos(ida_resultados)
    opciones = opciones_vuelo(ida_resultados)
    if elegir:
        opciones = elegir(opciones)
    for opcion in opciones:
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
                vuelos.append((precio, tramos_ida, tramos_vuelta, enlace_vuelos(regresos) or enlace_ida))
        if len(tokens) == 2:
            break
    return vuelos, registro


def extraer_alojamientos(hoteles):
    alojamientos = []
    for hotel in hoteles.get("properties", []):
        tarifa = hotel.get("total_rate") or {}
        precio = tarifa.get("extracted_after_taxes_fees")
        impuestos = importe_valido(precio)
        if not impuestos:
            precio = tarifa.get("extracted_display_price")
        if hotel.get("name") and importe_valido(precio):
            alojamientos.append((precio, hotel["name"], impuestos, hotel.get("overall_rating")))
    return alojamientos


def combinar_ofertas(vuelos, alojamientos):
    planes = [
        {"total": precio_vuelo + precio_hotel, "vuelo": precio_vuelo, "alojamiento": precio_hotel,
         "nombre": nombre, "ida": tramos_ida, "vuelta": tramos_vuelta, "impuestos_confirmados": impuestos,
         "enlace_vuelos": enlace, "nota_alojamiento": nota}
        for precio_vuelo, tramos_ida, tramos_vuelta, enlace in vuelos
        for precio_hotel, nombre, impuestos, nota in alojamientos
    ]
    planes.sort(key=lambda plan: (not plan["impuestos_confirmados"], plan["total"]))
    return planes
