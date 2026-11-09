"""Demo reproducible de coordinación y adaptación. Importes y horarios simulados."""

from dataclasses import dataclass
from contextlib import closing
import sqlite3


@dataclass(frozen=True)
class Opcion:
    nombre: str
    total: int
    llegada: int = 0
    cocina: bool = False


# Importes para una persona, ida y vuelta, y una habitación durante dos noches.
RUTAS = {
    "Valencia": {
        "Barcelona": (
            (Opcion("Tren nocturno", 65, 23), Opcion("Tren de tarde", 95, 19)),
            (Opcion("Hotel", 155), Opcion("Apartamento con cocina", 180, cocina=True)),
        ),
        "Zaragoza": (
            (Opcion("Autobús nocturno", 48, 23), Opcion("Tren de tarde", 76, 18)),
            (Opcion("Hostal", 110), Opcion("Apartamento con cocina", 135, cocina=True)),
        ),
    },
    "Sevilla": {
        "Málaga": (
            (Opcion("Autobús nocturno", 38, 23), Opcion("Tren de tarde", 64, 18)),
            (Opcion("Hotel", 120), Opcion("Apartamento con cocina", 145, cocina=True)),
        ),
        "Córdoba": (
            (Opcion("Autobús nocturno", 26, 23), Opcion("Tren de tarde", 48, 18)),
            (Opcion("Hostal", 92), Opcion("Apartamento con cocina", 112, cocina=True)),
        ),
    },
}

PREFERENCIAS = {
    "llegada_temprana": "Prefiero llegar antes de las 22:00",
    "cocina": "Prefiero un alojamiento con cocina",
}


class AgentePreferenciasViaje:
    def __init__(self, ruta_db):
        self.ruta_db = ruta_db
        with closing(sqlite3.connect(ruta_db)) as conexion, conexion:
            conexion.execute(
                "CREATE TABLE IF NOT EXISTS correcciones_plan ("
                "viaje TEXT, preferencia TEXT, PRIMARY KEY (viaje, preferencia))"
            )

    def aprender(self, viaje, preferencia):
        if preferencia not in PREFERENCIAS:
            raise ValueError("Preferencia desconocida.")
        with closing(sqlite3.connect(self.ruta_db)) as conexion, conexion:
            conexion.execute("INSERT OR IGNORE INTO correcciones_plan VALUES (?, ?)", (viaje, preferencia))

    def perfil(self):
        with closing(sqlite3.connect(self.ruta_db)) as conexion:
            return dict(conexion.execute("SELECT preferencia, COUNT(*) FROM correcciones_plan GROUP BY preferencia"))


class AgenteDestino:
    def proponer(self, origen):
        return RUTAS[origen].items()


class AgenteTransporte:
    def penalizacion(self, opcion, perfil, permitir_tarde):
        return perfil.get("llegada_temprana", 0) if opcion.llegada >= 22 and not permitir_tarde else 0


class AgenteAlojamiento:
    def penalizacion(self, opcion, perfil):
        return 0 if opcion.cocina else perfil.get("cocina", 0)


@dataclass(frozen=True)
class Plan:
    ciudad: str
    transporte: Opcion
    alojamiento: Opcion

    @property
    def total(self):
        return self.transporte.total + self.alojamiento.total


def coordinar(origen, presupuesto, perfil, permitir_tarde=False, cancelado=None):
    """Prueba alternativas y conserva el alojamiento cuando repara un transporte."""
    trazas = []
    destinos = AgenteDestino()
    transporte = AgenteTransporte()
    alojamiento = AgenteAlojamiento()
    ciudades = destinos.proponer(origen)
    if cancelado:
        trazas.append(f"Coordinación · {cancelado.transporte.nombre} cancelado en {cancelado.ciudad}.")
        ciudades = sorted(ciudades, key=lambda entrada: entrada[0] != cancelado.ciudad)
    for ciudad, (viajes, estancias) in ciudades:
        trazas.append(f"Destino · Considera {ciudad} desde {origen}.")
        if cancelado and ciudad == cancelado.ciudad:
            viajes = [opcion for opcion in viajes if opcion != cancelado.transporte]
        trazas.append("Transporte · " + ", ".join(f"{o.nombre} ({o.total} €)" for o in viajes))
        trazas.append("Alojamiento · " + ", ".join(f"{o.nombre} ({o.total} €)" for o in estancias))
        planes = [Plan(ciudad, viaje, estancia) for estancia in estancias for viaje in viajes]
        planes.sort(key=lambda plan: (
            bool(cancelado and ciudad == cancelado.ciudad and plan.alojamiento != cancelado.alojamiento),
            transporte.penalizacion(plan.transporte, perfil, permitir_tarde)
            + alojamiento.penalizacion(plan.alojamiento, perfil),
            plan.total,
        ))
        for plan in planes:
            if plan.total <= presupuesto:
                trazas.append(f"Coordinación · Verifica {plan.total} € dentro del límite de {presupuesto} €.")
                return plan, trazas
            trazas.append(f"Coordinación · Descarta {plan.transporte.nombre} + {plan.alojamiento.nombre}: {plan.total} € supera {presupuesto} €.")
    return None, trazas
