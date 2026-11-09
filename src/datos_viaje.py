"""Datos documentados y valoraciones del perfil local en SQLite."""

from collections import Counter
from contextlib import closing
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
