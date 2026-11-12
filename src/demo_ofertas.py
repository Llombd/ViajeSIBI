"""Catálogo ficticio para practicar la planificación sin servicios externos."""

from datetime import date, timedelta

def consultar_catalogo_ficticio(parametros):
    """Devuelve el mismo formato que SerpApi a partir de tarifas sintéticas."""
    from src.ofertas_reales import TIPOS_ALOJAMIENTO
    from src.seleccion_viaje import CIUDADES

    adultos = parametros["adults"]
    if parametros["engine"] == "google_hotels":
        ciudad = parametros["q"]
        entrada = date.fromisoformat(parametros["check_in_date"])
        salida = date.fromisoformat(parametros["check_out_date"])
        noches = (salida - entrada).days
        tipos = parametros.get("property_types")
        permitidos = set(tipos.split(",")) if tipos else None
        base = 12 + sum(map(ord, ciudad)) % 55
        noches_fin_semana = sum((entrada + timedelta(days=i)).weekday() >= 4 for i in range(noches))
        propiedades = []
        for nombre, codigo in TIPOS_ALOJAMIENTO.items():
            if permitidos is not None and str(codigo) not in permitidos:
                continue
            for zona, suplemento, ajuste_nota in (
                ("Centro", 18, 1.0), ("Estación", 8, 0.5), ("Barrio exterior", 0, 0.0),
            ):
                tarifa = base + (codigo % 7) * 8 + suplemento
                propiedades.append({
                    "name": f"{nombre} · {zona} · {ciudad} (ficticio)",
                    "overall_rating": min(5.0, 3 + (codigo % 5) * 0.5 + ajuste_nota),
                    "total_rate": {"extracted_after_taxes_fees":
                                   (tarifa * noches + 8 * noches_fin_semana) * adultos},
                })
        return {"properties": propiedades}

    origen, destino = parametros["departure_id"], parametros["arrival_id"]
    ida = date.fromisoformat(parametros["outbound_date"])
    turno_ida = parametros.get("departure_token")
    horarios = {"manana": (8, 25), "tarde": (16, 0)}

    def tramo(salida, llegada, dia, hora, numero):
        return {
            "flight_number": numero, "airline": "Aerolínea ficticia",
            "departure_airport": {"id": salida, "name": CIUDADES[salida], "time": f"{dia} {hora:02d}:00"},
            "arrival_airport": {"id": llegada, "name": CIUDADES[llegada], "time": f"{dia} {hora + 2:02d}:00"},
        }

    if turno_ida is None:
        return {"best_flights": [
            {"flights": [tramo(origen, destino, parametros["outbound_date"], hora, f"SIM-01{i}")],
             "departure_token": turno}
            for i, (turno, (hora, _)) in enumerate(horarios.items(), 1)
        ]}
    _, suplemento_ida = horarios[turno_ida]
    base = 55 + sum(map(ord, origen + destino)) % 180 + 10 * ida.weekday()
    return {"best_flights": [
        {"flights": [tramo(destino, origen, parametros["return_date"], hora, f"SIM-02{i}")],
         "price": (base + suplemento_ida + suplemento) * adultos}
        for i, (hora, suplemento) in enumerate(horarios.values(), 1)
    ]}
