"""Defensa visible del proyecto con informes locales, sin ejecutar modelos ni API."""
import json
from pathlib import Path

import streamlit as st

from src.balance_comparacion import balance_comparacion

RAIZ = Path(__file__).resolve().parents[1]


def resumen_piloto(informe):
    filas = []
    for caso in informe.get("casos", []):
        if caso.get("error"):
            filas.append({"Origen": caso["origen"], "Presupuesto grupo": caso["presupuesto"],
                          "Resultado": "Error del modelo"})
            continue
        balance = balance_comparacion(caso["estrategias"], caso["presupuesto"])
        fila = {"Origen": caso["origen"], "Presupuesto grupo": caso["presupuesto"],
                "Resultado": balance["categoria"]}
        for nombre, metodo in zip(("Plan inicial", "Agente"), balance["metodos"]):
            fila[f"{nombre}: total confirmado"] = metodo["total"]
            fila[f"{nombre}: consultas"] = metodo["consultas"]
            fila[f"{nombre}: llamadas Qwen3"] = metodo["llamadas_modelo"]
        filas.append(fila)
    return filas


def mostrar_evidencia():
    st.header("Qué hace el agente y cómo comprobarlo")
    st.write("Delegas un objetivo: encontrar un viaje respetando tus condiciones. "
             "El planificador decide qué consulta hacer, recibe resultados y puede revisar su elección.")
    st.subheader("Quién hace cada trabajo")
    st.table([
        {"Parte": "Coordinación · Qwen3", "Trabajo": "Encarga consultas a los especialistas y revisa el coste conjunto."},
        {"Parte": "Destinos · Qwen3", "Trabajo": "Elige ciudad y fechas con los gustos y los informes recibidos."},
        {"Parte": "Transporte · Qwen3", "Trabajo": "Decide la ordenación de vuelos y qué regresos comprobar."},
        {"Parte": "Alojamiento · Qwen3", "Trabajo": "Decide cómo buscar estancias con el presupuesto disponible."},
        {"Parte": "Mejora · Qwen3 (laboratorio)", "Trabajo": "Propone mantener la estrategia o probar el uso de experiencia repetida."},
        {"Parte": "Herramientas de vuelos y alojamiento", "Trabajo": "Consultan datos. Son funciones, no agentes LLM independientes."},
        {"Parte": "Control · Python", "Trabajo": "Valida acciones, combina precios, aplica límites y mide resultados."},
        {"Parte": "Memoria · SQLite", "Trabajo": "Conserva prioridades confirmadas, búsquedas y experimentos."},
    ])
    st.markdown("**Objetivo → elección del modelo → consulta → resultado observado → nueva decisión → comprobación.**")
    st.caption("Python propone un orden de exploración para no insistir siempre en la misma ciudad. "
               "Con total confirmado se exploran otros destinos; si faltan datos, se admiten otras fechas. "
               "Qwen3 elige entre las combinaciones autorizadas. La planificación usa cuatro roles con historiales separados en el mismo modelo local.")
    st.subheader("Qué diferencia estamos midiendo")
    st.write("La comparación actual enfrenta un agente con herramientas al equipo de cuatro, usando el mismo Qwen3. Los informes históricos comparan la lista inicial y el planificador anterior: una lista fijada al principio "
             "frente a decisiones revisables. Buscamos más viajes válidos, menor coste o menos consultas. "
             "También mostramos cuándo el agente empata, falla o resulta peor.")
    st.info("Una IA con herramientas y un bucle de decisiones también es un agente. "
            "Este proyecto no prueba superioridad frente a Gemini, ChatGPT o Booking.")
    st.subheader("Pruebas con el modelo real, sin gastar la API")
    archivos = sorted((RAIZ / "evals").glob("resultado_revision_*.json"), reverse=True)
    if archivos:
        archivo = st.selectbox("Informe del piloto", archivos, format_func=lambda p: p.name)
        try:
            informe = json.loads(archivo.read_text())
            st.caption(f"Modelo: {informe['modelo']} · Datos: {informe['datos']} · Ejecución: {informe['fecha_utc']}")
            st.table(resumen_piloto(informe))
            st.download_button("Descargar evidencia completa", archivo.read_bytes(), file_name=archivo.name,
                               mime="application/json")
        except (OSError, ValueError, KeyError):
            st.warning("No se pudo leer este informe. No se presenta como una prueba superada.")
    else:
        st.info("Aún no hay un informe del piloto guardado.")
    st.caption("Son casos de desarrollo con ofertas ficticias; repetirlos tras ajustar el programa no es "
               "una validación independiente. Los informes anteriores se conservan, incluidos los desfavorables.")
    anterior = RAIZ / "evals" / "resultado_equipo_antes_2026-11-15.json"
    mejora = RAIZ / "evals" / "resultado_equipo_mejora_2026-11-15.json"
    if anterior.exists() and mejora.exists():
        st.subheader("Qué mejoró al revisar el equipo")
        antes = json.loads(anterior.read_text())["casos"]
        despues = json.loads(mejora.read_text())["casos"]
        tabla = []
        for previo, nuevo in zip(antes, despues):
            tabla.append({
                "Origen": previo["origen"], "Presupuesto grupo": previo["presupuesto"],
                "Equipo anterior": previo["equipo"]["total"],
                "Equipo revisado": nuevo["equipo"]["total"],
                "Un agente": nuevo["un_agente"]["total"],
                "Decisiones antes": previo["equipo"]["llamadas_modelo"],
                "Decisiones después": nuevo["equipo"]["llamadas_modelo"],
                "Consultas antes": previo["equipo"]["consultas"],
                "Consultas después": nuevo["equipo"]["consultas"],
            })
        st.table(tabla)
        st.caption("Qwen3 real, datos ficticios y los mismos tres encargos, con hasta 12 consultas "
                   "por método. El equipo revisado encontró viajes más baratos que su versión previa, "
                   "pero el agente único consiguió mejores precios. Son casos de desarrollo. "
                   "La comprobación final posterior en Valencia dio 570 €, peor que los 500 € de esta "
                   "tabla y que los 470 € del agente único. Todavía no hay una mejora estable "
                   "demostrada del equipo frente al agente único.")
    st.subheader("Qué aprende y qué sigue pendiente")
    st.write("Las prioridades se guardan con tu confirmación. Tras rechazos repetidos de otra salida, "
             "se propone recordar tu aeropuerto. El laboratorio ensaya cambiar la estrategia, "
             "pero solo la conserva si supera sus pruebas; no reentrena Qwen3.")
    st.write("Falta demostrar una ventaja consistente con una muestra independiente de ofertas reales. "
             "Los gustos libres orientan al modelo; vuelos y hoteles no verifican por sí solos playa, gastronomía o ambiente.")
    guia = RAIZ / "evals" / "guion_profesor.md"
    if guia.exists():
        st.download_button("Descargar guion para explicarlo en clase", guia.read_bytes(),
                           file_name="guion-profesor-viajesibi.md", mime="text/markdown")
