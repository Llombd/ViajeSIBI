"""Comparación del planificador de un agente con el equipo de cuatro."""
from time import monotonic

from src.equipo_viaje import EquipoViaje
from src.seleccion_viaje import (
    proponer_busquedas, decidir_siguiente_busqueda, explorar_ofertas,
)


def comparar_un_agente_y_equipo(cliente, consultar, origen, fechas, gustos, adultos, presupuesto):
    """Mismo encargo, ofertas y máximo de 12 consultas y tres destinos/fechas."""
    propuestas = proponer_busquedas(cliente, origen, fechas, gustos, adultos, presupuesto)
    observaciones = []
    inicio = monotonic()
    planes, traza, _ = explorar_ofertas(
        consultar, origen, propuestas, adultos, presupuesto,
        replantear=lambda datos: decidir_siguiente_busqueda(
            cliente, origen, fechas, gustos, adultos, presupuesto, datos, propuestas,
        ),
        fechas=fechas, observaciones=observaciones, limite_intentos=3,
        conservar_pendientes=True, limite_total=presupuesto,
    )
    traza.append(f"Tiempo del agente único tras la propuesta inicial: {monotonic() - inicio:.1f} s.")
    equipo = EquipoViaje(cliente, consultar, max_consultas=12)
    planes_equipo, pasos_equipo, _ = equipo.planificar(
        origen, fechas, gustos, adultos, presupuesto, intentos=3, objetivo=3,
    )
    return [
        ("Un agente con herramientas", observaciones, planes, traza),
        ("Equipo de cuatro agentes", equipo.informes, planes_equipo, pasos_equipo),
    ]
