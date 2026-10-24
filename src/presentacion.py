"""Presentación en terminal de opciones ya validadas, sin llamadas al modelo."""


def _etiquetas(intereses):
    # Solo cambia la escritura de una etiqueta; no añade características.
    return ", ".join("gastronomía" if i == "gastronomia" else i for i in sorted(intereses))


def _dinero(importe):
    return f"{importe:g} EUR"


def _tabla(cabecera, filas):
    """Alinea columnas con texto; no requiere librerías ni una interfaz gráfica."""
    anchos = [max(len(fila[i]) for fila in [cabecera, *filas]) for i in range(len(cabecera))]

    def linea(fila):
        return "| " + " | ".join(celda.ljust(ancho) for celda, ancho in zip(fila, anchos)) + " |"

    separador = "|-" + "-|-".join("-" * ancho for ancho in anchos) + "-|"
    return "\n".join([linea(cabecera), separador, *(linea(fila) for fila in filas)])


def presentar_opciones(opciones, presupuesto, intereses, tipo):
    """Recibe pares (destino del catálogo, resultado de estimar_coste).

    El agente comprueba antes los IDs, parámetros y presupuesto. Aquí solo se
    ordenan esas opciones y se construye texto a partir de sus datos.
    """
    ordenadas = sorted(opciones, key=lambda opcion: opcion[1]["total_grupo"])
    viaje = ordenadas[0][1]
    lineas = [
        "Datos del viaje",
        f"Origen: {viaje['origen']} | Duración y viajeros: "
        f"{viaje['duracion_dias']} días, {viaje['viajeros']} viajeros",
        "Presupuesto total: " + (_dinero(presupuesto) if presupuesto is not None else "No indicado"),
        "Intereses: " + (_etiquetas(intereses) if intereses else "No indicados"),
        "",
        "Destinos recomendados con coste comprobado:" if tipo == "recomendacion" else "Costes consultados:",
    ]
    filas = []
    for destino, coste in ordenadas:
        margen = round(presupuesto - coste["total_grupo"], 2) if presupuesto is not None else None
        filas.append([
            destino["nombre"],
            destino["pais"],
            _dinero(coste["total_grupo"]),
            _dinero(coste["total_por_persona"]),
            _dinero(margen) if margen is not None else "No disponible",
            _etiquetas(destino["intereses"]),
        ])
    lineas.append(_tabla(
        ["Destino", "País", "Coste total", "Por persona", "Margen disponible", "Características"],
        filas,
    ))
    lineas.extend(["", "Por qué se proponen:" if tipo == "recomendacion" else "Detalle de las opciones:"])
    for destino, coste in ordenadas:
        coincidentes = intereses.intersection(destino["intereses"])
        if coincidentes:
            motivo = f"Coincide con tus intereses en {_etiquetas(coincidentes)}."
        elif intereses:
            motivo = ("No hay coincidencia con los intereses indicados. "
                      f"El catálogo registra {_etiquetas(destino['intereses'])}.")
        else:
            motivo = (f"El catálogo registra {_etiquetas(destino['intereses'])}. "
                      "No indicaste intereses específicos.")
        if tipo == "recomendacion":
            motivo += " Su coste comprobado está dentro del presupuesto."
        lineas.append(f"- {destino['nombre']}: {motivo}")
    lineas.extend([
        "",
        "Orden por coste entre las opciones mostradas; no es una clasificación de todo el catálogo.",
        "El coste incluye transporte de ida y vuelta, alojamiento y gastos diarios.",
        "Datos ficticios del catálogo y las herramientas, no ofertas reales.",
    ])
    return "\n".join(lineas)
