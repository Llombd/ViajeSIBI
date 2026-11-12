"""Experiencia local contextual. Los precios recordados nunca sustituyen consultas."""
from contextlib import closing
from datetime import date
import json
from math import isfinite
import sqlite3

from src.datos_viaje import DatosViaje


def contexto_viaje(origen, adultos, noches, gustos, fuente="ficticio-v1", tipos=None, nota=0):
    # La separación de fuente impide transferir precios inventados a búsquedas reales.
    return json.dumps(dict(origen=origen, adultos=adultos, noches=noches,
                           gustos=sorted(g.strip().casefold() for g in gustos.split(",") if g.strip()),
                           fuente=fuente, tipos=sorted(tipos) if tipos is not None else None, nota=nota),
                      sort_keys=True, ensure_ascii=False)


class MemoriaBusquedas:
    def __init__(self, ruta=None):
        self.ruta = DatosViaje(ruta).ruta
        with closing(sqlite3.connect(self.ruta)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS experiencia_busquedas (contexto TEXT, aeropuerto TEXT, "
                       "ida TEXT, vuelta TEXT, total REAL, PRIMARY KEY(contexto,aeropuerto,ida,vuelta))")
            db.execute("CREATE TABLE IF NOT EXISTS experimentos_mejora (id TEXT PRIMARY KEY, "
                       "contexto TEXT, datos TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS estrategias_aprendidas (contexto TEXT PRIMARY KEY, "
                       "experimento TEXT, estrategia TEXT NOT NULL)")

    def registrar(self, contexto, observaciones):
        filas = []
        for o in observaciones:
            total = o.get("total")
            if (o.get("impuestos_confirmados") is not True or type(total) not in (int, float)
                    or not isfinite(total) or total <= 0):
                continue
            # Solo guardamos campos estructurados de la herramienta, no prompts ni claves.
            ida, vuelta = date.fromisoformat(o["ida"]), date.fromisoformat(o["vuelta"])
            if ida >= vuelta or (vuelta-ida).days != json.loads(contexto)["noches"]:
                raise ValueError("Fechas de experiencia inválidas")
            filas.append((contexto, o["aeropuerto"], ida.isoformat(), vuelta.isoformat(), total))
        with closing(sqlite3.connect(self.ruta)) as db, db:
            db.executemany("INSERT OR REPLACE INTO experiencia_busquedas VALUES (?,?,?,?,?)", filas)

    def recordar(self, contexto, presupuesto):
        with closing(sqlite3.connect(self.ruta)) as db:
            filas = db.execute("SELECT aeropuerto, COUNT(*), AVG(total), MIN(total), MAX(total), "
                               "GROUP_CONCAT(ida) FROM experiencia_busquedas WHERE contexto=? "
                               "GROUP BY aeropuerto HAVING COUNT(*)>=2 AND MAX(total)<=? "
                               "ORDER BY AVG(total), aeropuerto LIMIT 3", (contexto, presupuesto)).fetchall()
        return [dict(aeropuerto=c, observaciones=n, media_historica=round(media, 2),
                     minimo_historico=menor, maximo_historico=mayor, fechas_observadas=sorted(fechas.split(",")))
                for c, n, media, menor, mayor, fechas in filas]

    def guardar_experimento(self, informe):
        # La decisión se recalcula a partir de las mediciones, no de la opinión del LLM.
        from src.mejora_agente import validar_mejora
        if json.loads(informe["contexto"])["fuente"] != informe.get("fuente"):
            raise ValueError("La fuente de la experiencia no coincide con la del experimento.")
        aprobado, motivo = validar_mejora(informe.get("validacion", []), informe.get("limites", {}).get("presupuesto", 500))
        if informe.get("propuesta", {}).get("estrategia") != "priorizar_exitos":
            aprobado, motivo = False, "No se propuso una estrategia nueva respaldada por experiencia repetida."
        citadas = informe.get("propuesta", {}).get("evidencias", [])
        experiencia = informe.get("experiencia", [])
        disponibles = {e["aeropuerto"]: e for e in self.recordar(informe["contexto"],
                       informe.get("limites", {}).get("presupuesto", 500))}
        if (not citadas or not set(citadas).issubset(disponibles)
                or any(e not in experiencia for c, e in disponibles.items() if c in citadas)):
            aprobado, motivo = False, "La propuesta no está respaldada por la experiencia repetida guardada."
        reservadas = {p["sin_memoria"]["ida"] for p in informe.get("validacion", [])}
        aprendidas = {d for e in informe.get("experiencia", []) for d in e.get("fechas_observadas", [])}
        if reservadas & aprendidas:
            aprobado, motivo = False, "Las fechas de validación ya aparecen en la experiencia: prueba contaminada."
        informe = {**informe, "adoptada": aprobado, "motivo_validacion": motivo}
        with closing(sqlite3.connect(self.ruta)) as db, db:
            db.execute("INSERT OR REPLACE INTO experimentos_mejora VALUES (?,?,?)",
                       (informe["id"], informe["contexto"], json.dumps(informe)))
            if aprobado:
                db.execute("INSERT OR REPLACE INTO estrategias_aprendidas VALUES (?,?,?)",
                           (informe["contexto"], informe["id"], "priorizar_exitos"))
        return informe

    def activa(self, contexto):
        with closing(sqlite3.connect(self.ruta)) as db:
            fila = db.execute("SELECT experimento, estrategia FROM estrategias_aprendidas WHERE contexto=?",
                              (contexto,)).fetchone()
        return dict(experimento=fila[0], estrategia=fila[1]) if fila else None

    def experimentos(self, contexto):
        with closing(sqlite3.connect(self.ruta)) as db:
            filas = db.execute("SELECT datos FROM experimentos_mejora WHERE contexto=? ORDER BY rowid DESC",
                               (contexto,)).fetchall()
        return [json.loads(f[0]) for f in filas]

    def experiencia_validada(self, contexto, presupuesto):
        """Recupera solo la evidencia seleccionada en la política que superó la prueba.

        Nuevas observaciones no amplían silenciosamente una política ya validada.
        """
        activa = self.activa(contexto)
        if not activa:
            return []
        with closing(sqlite3.connect(self.ruta)) as db:
            fila = db.execute("SELECT datos FROM experimentos_mejora WHERE id=? AND contexto=?",
                              (activa["experimento"], contexto)).fetchone()
        if not fila:
            return []
        informe = json.loads(fila[0])
        seleccion = informe.get("propuesta", {}).get("evidencias", [])
        return [e for e in informe.get("experiencia", [])
                if e["aeropuerto"] in seleccion and e["media_historica"] <= presupuesto]
