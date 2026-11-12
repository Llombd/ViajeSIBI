"""Datos documentados y valoraciones del perfil local en SQLite."""

from collections import Counter
from contextlib import closing
from datetime import date
import json
import os
from pathlib import Path
import sqlite3


RAIZ = Path(__file__).resolve().parent.parent


class DatosViaje:
    def __init__(self, ruta=None):
        self.ruta = Path(ruta or os.environ.get("VIAJESIBI_DB") or RAIZ / ".viajesibi.sqlite3")
        with closing(sqlite3.connect(self.ruta)) as conexion, conexion:
            conexion.execute(
                "CREATE TABLE IF NOT EXISTS lugares ("
                "destino_id TEXT PRIMARY KEY, nombre TEXT NOT NULL, url TEXT NOT NULL)"
            )
            conexion.execute(
                "CREATE TABLE IF NOT EXISTS valoraciones ("
                "destino_id TEXT PRIMARY KEY, valor INTEGER NOT NULL CHECK(valor IN (-1, 1)))"
            )
            conexion.execute(
                "CREATE TABLE IF NOT EXISTS demostraciones_ofertas ("
                "id TEXT PRIMARY KEY, fecha TEXT NOT NULL, datos TEXT NOT NULL)"
            )
            conexion.execute(
                "CREATE TABLE IF NOT EXISTS comparaciones_ofertas ("
                "id TEXT PRIMARY KEY, fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, datos TEXT NOT NULL)"
            )
            lugares = json.loads((RAIZ / "data" / "lugares_verificados.json").read_text(encoding="utf-8"))
            conexion.executemany(
                "INSERT OR IGNORE INTO lugares VALUES (:destino_id, :nombre, :url)", lugares,
            )

    def prioridades_ofertas(self):
        with closing(sqlite3.connect(self.ruta)) as conexion:
            conexion.execute("CREATE TABLE IF NOT EXISTS prioridades_ofertas (id INTEGER PRIMARY KEY, datos TEXT)")
            fila = conexion.execute("SELECT datos FROM prioridades_ofertas WHERE id = 1").fetchone()
        return json.loads(fila[0]) if fila else {}

    def guardar_prioridades_ofertas(self, prioridades):
        with closing(sqlite3.connect(self.ruta)) as conexion, conexion:
            conexion.execute("CREATE TABLE IF NOT EXISTS prioridades_ofertas (id INTEGER PRIMARY KEY, datos TEXT)")
            conexion.execute("INSERT OR REPLACE INTO prioridades_ofertas VALUES (1, ?)", (json.dumps(prioridades),))

    def registrar_rechazo_salida(self, origen, busqueda):
        """Cuenta una sola decisión por búsqueda y aeropuerto de origen."""
        with closing(sqlite3.connect(self.ruta)) as conexion, conexion:
            conexion.execute(
                "CREATE TABLE IF NOT EXISTS rechazos_salida ("
                "origen TEXT NOT NULL, busqueda TEXT NOT NULL, PRIMARY KEY (origen, busqueda))"
            )
            conexion.execute("INSERT OR IGNORE INTO rechazos_salida VALUES (?, ?)", (origen, busqueda))
            return conexion.execute(
                "SELECT COUNT(*) FROM rechazos_salida WHERE origen = ?", (origen,),
            ).fetchone()[0]

    def guardar_comparacion(self, identificador, resultados, presupuesto, simulada=True):
        # La reproducción solo necesita el total, los intentos y las trazas.
        filas = [(nombre, intentos, [{"total": plan["total"], "impuestos_confirmados": plan.get("impuestos_confirmados", True)}
                                   for plan in planes], traza)
                 for nombre, intentos, planes, traza in resultados]
        with closing(sqlite3.connect(self.ruta)) as conexion, conexion:
            conexion.execute(
                "INSERT OR IGNORE INTO comparaciones_ofertas (id, datos) VALUES (?, ?)",
                (identificador, json.dumps([filas, presupuesto, simulada])),
            )

    def comparaciones_guardadas(self):
        with closing(sqlite3.connect(self.ruta)) as conexion:
            filas = conexion.execute(
                "SELECT fecha, datos FROM comparaciones_ofertas ORDER BY fecha DESC, rowid DESC"
            ).fetchall()
        return [(fecha, json.loads(datos)) for fecha, datos in filas]

    def guardar_demostracion(self, resultado):
        planes, registro, primero, limite, origen, personas, margen, busqueda = resultado
        planes_json = [
            {**plan, "ida_fecha": plan["ida_fecha"].isoformat(), "vuelta_fecha": plan["vuelta_fecha"].isoformat()}
            for plan in planes
        ]
        contenido = json.dumps([planes_json, registro, primero, limite, origen, personas, margen, busqueda])
        with closing(sqlite3.connect(self.ruta)) as conexion, conexion:
            conexion.execute(
                "INSERT OR IGNORE INTO demostraciones_ofertas (id, fecha, datos) VALUES (?, CURRENT_TIMESTAMP, ?)",
                (busqueda, contenido),
            )

    def demostraciones(self):
        with closing(sqlite3.connect(self.ruta)) as conexion:
            filas = conexion.execute(
                "SELECT fecha, datos FROM demostraciones_ofertas ORDER BY fecha DESC, rowid DESC"
            ).fetchall()
        resultados = []
        for fecha, contenido in filas:
            resultado = json.loads(contenido)
            for plan in resultado[0]:
                for campo in ("ida_fecha", "vuelta_fecha"):
                    plan[campo] = date.fromisoformat(plan[campo])
            resultados.append((fecha, resultado))
        return resultados

    def lugar(self, destino_id):
        with closing(sqlite3.connect(self.ruta)) as conexion:
            fila = conexion.execute(
                "SELECT nombre, url FROM lugares WHERE destino_id = ?", (destino_id,),
            ).fetchone()
        return {"nombre": fila[0], "url": fila[1], "fuente": "UNESCO"} if fila else None

    def valorar(self, destino_id, valor):
        with closing(sqlite3.connect(self.ruta)) as conexion, conexion:
            conexion.execute(
                "INSERT INTO valoraciones VALUES (?, ?) "
                "ON CONFLICT(destino_id) DO UPDATE SET valor = excluded.valor",
                (destino_id, valor),
            )

    def valoraciones(self):
        with closing(sqlite3.connect(self.ruta)) as conexion:
            return dict(conexion.execute("SELECT destino_id, valor FROM valoraciones"))


class AgenteDatos:
    """Aporta evidencia verificable para un destino, si existe cobertura."""

    def __init__(self, datos):
        self.datos = datos

    def enriquecer(self, destino):
        lugar = self.datos.lugar(destino["id"])
        return {**destino, "lugar_verificado": lugar} if lugar else destino


class AgentePreferencias:
    """Aprende de valoraciones explícitas y ordena candidatos ya filtrados."""

    def __init__(self, datos, catalogo):
        self.datos = datos
        self.intereses_por_destino = {d["id"]: d["intereses"] for d in catalogo}

    def perfil(self, votos):
        perfil = Counter()
        for destino_id, voto in votos.items():
            for interes in self.intereses_por_destino.get(destino_id, ()):
                perfil[interes] += voto
        return dict(perfil)

    def priorizar(self, destinos):
        votos = self.datos.valoraciones()
        if not votos:
            return destinos, {}
        perfil = self.perfil(votos)
        priorizados = sorted(
            destinos,
            key=lambda destino: (
                votos.get(destino["id"], 0),
                sum(perfil.get(interes, 0) for interes in destino["intereses"]),
            ),
            reverse=True,
        )
        return priorizados, perfil
