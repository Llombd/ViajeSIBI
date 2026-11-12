"""Resultados para explicar el valor de la búsqueda sin vocabulario técnico."""


def medir_resultado(fila, presupuesto):
    nombre, intentos, planes, _ = fila
    confirmados = [p["total"] for p in planes if p.get("impuestos_confirmados", True)]
    total = min(confirmados, default=None)
    consultas = (sum(i["consultas_proveedor"] for i in intentos)
                 if intentos and all("consultas_proveedor" in i for i in intentos) else None)
    return {
        "metodo": nombre, "total": total,
        "viable": total is not None and total <= presupuesto,
        "consultas": consultas,
        # Cada método recibe la misma propuesta inicial (una llamada compartida).
        "llamadas_modelo": (1 + sum(i["llamadas_revision"] for i in intentos)
                             if intentos and all("llamadas_revision" in i for i in intentos) else None),
        "revisiones_invalidas": (sum(i.get("revision_estado") == "invalida" for i in intentos)
                                  if intentos and all("llamadas_revision" in i for i in intentos) else None),
        "hoteles_evitados": sum(i.get("diagnostico", {}).get("consultas_hotel_evitadas", 0)
                                for i in intentos),
        "cambios": sum(i.get("revision_aplicada", False) for i in intentos),
    }


def balance_comparacion(resultados, presupuesto):
    """No confunde un precio menor fuera de presupuesto con un viaje conseguido."""
    fija, agente = [medir_resultado(fila, presupuesto) for fila in resultados]
    ahorro = None
    if agente["viable"] and not fija["viable"]:
        titulo = "El agente encontró un viaje dentro del presupuesto; la lista inicial no."
        categoria = "Solo el agente consiguió un viaje"
    elif fija["viable"] and not agente["viable"]:
        titulo = "La lista inicial encontró un viaje dentro del presupuesto; el agente no."
        categoria = "Solo la lista consiguió un viaje"
    elif fija["viable"] and agente["viable"]:
        ahorro = fija["total"] - agente["total"]
        if ahorro > 0:
            titulo = f"Ambos encontraron viaje. La opción del agente cuesta {ahorro:.2f} € menos para el grupo."
            categoria = "Ambos consiguieron viaje; agente más barato"
        elif ahorro < 0:
            titulo = f"Ambos encontraron viaje. La lista inicial consiguió una opción {-ahorro:.2f} € más barata."
            categoria = "Ambos consiguieron viaje; lista más barata"
        else:
            titulo = "Ambos encontraron viaje al mismo precio. No hubo mejora de precio en esta búsqueda."
            categoria = "Mismo resultado y precio"
    else:
        titulo = "Ninguno consiguió un viaje con total confirmado dentro del presupuesto."
        categoria = "Ninguno consiguió un viaje confirmado"
    return {"titulo": titulo, "categoria": categoria, "ahorro": ahorro,
            "metodos": [fija, agente]}
