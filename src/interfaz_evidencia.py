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
        {"Parte": "Planificador · Qwen3", "Trabajo": "Elige destino y fechas; decide de nuevo tras observar precios o falta de ofertas."},
        {"Parte": "Mejora · Qwen3 (laboratorio)", "Trabajo": "Propone mantener la estrategia o probar el uso de experiencia repetida."},
        {"Parte": "Herramientas de vuelos y alojamiento", "Trabajo": "Consultan datos. Son funciones, no agentes LLM independientes."},
        {"Parte": "Control · Python", "Trabajo": "Valida acciones, combina precios, aplica límites y mide resultados."},
        {"Parte": "Memoria · SQLite", "Trabajo": "Conserva prioridades confirmadas, búsquedas y experimentos."},
    ])
    st.markdown("**Objetivo → elección del modelo → consulta → resultado observado → nueva decisión → comprobación.**")
    st.caption("Python propone un orden de exploración para no insistir siempre en la misma ciudad. "
               "Con total confirmado se exploran otros destinos; si faltan datos, se admiten otras fechas. "
               "Qwen3 elige entre las combinaciones autorizadas. Las capas no son cinco agentes autónomos.")
    st.subheader("Qué diferencia estamos midiendo")
    st.write("La comparación usa el mismo Qwen3 y las mismas herramientas: una lista fijada al principio "
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
