"""Laboratorio visible: experiencia, hipótesis, prueba reservada y decisión."""
from datetime import date
import json
import streamlit as st
from src.agent import ClienteOllama, ErrorOllama
from src.demo_ofertas import consultar_catalogo_ficticio
from src.memoria_busquedas import MemoriaBusquedas
from src.mejora_agente import CONTEXTO_LAB, PRESUPUESTO_LAB, practicar, experimentar, ejecutar_caso
from src.seleccion_viaje import CIUDADES


def mostrar_informe(informe):
    st.subheader("3. ¿La mejora superó la prueba?")
    st.write(informe["propuesta"]["hipotesis"])
    filas = []
    for par in informe["validacion"]:
        for clave, nombre in (("sin_memoria", "Sin experiencia"), ("con_memoria", "Con experiencia")):
            r = par[clave]
            filas.append({"Salida": r["ida"], "Estrategia": nombre,
                          "Viaje válido": "Sí" if r["viaje_encontrado"] else "No",
                          "Total grupo": f"{r['total']:.2f} €" if r["total"] is not None else "Sin total",
                          "Consultas de ofertas": r["consultas"], "Llamadas a Qwen3": r["llamadas_modelo"],
                          "Segundos": r["segundos"]})
    if filas:
        st.table(filas)
        coste_datos = sum(r["consultas"] for par in informe["validacion"] for r in par.values())
        coste_modelo = 1 + sum(r["llamadas_modelo"] for par in informe["validacion"] for r in par.values())
        st.caption(f"Inversión en esta prueba: {coste_datos} consultas de ofertas ficticias y "
                   f"{coste_modelo} llamadas a Qwen3, incluida la propuesta de mejora. "
                   "Las búsquedas previas de práctica se añaden a ese trabajo. Una mejora posterior no recupera automáticamente ese coste.")
    if informe["adoptada"]:
        st.success("Estrategia guardada: priorizar destinos con éxitos anteriores en viajes comparables.")
        pares = informe["validacion"]
        antes = sum(p["sin_memoria"]["consultas"] for p in pares)
        despues = sum(p["con_memoria"]["consultas"] for p in pares)
        mismo_coste = all(p["sin_memoria"]["total"] == p["con_memoria"]["total"] for p in pares)
        if despues < antes:
            st.info(f"En estas {len(pares)} pruebas: {antes} → {despues} consultas de ofertas. "
                    + ("Se encontraron viajes al mismo precio." if mismo_coste else
                       "La tabla muestra el resultado y precio de cada viaje."))
        st.write("Qué cambió: el planificador recibe la experiencia de destinos que funcionaron "
                 "repetidamente y los considera primero. Sigue comprobando vuelos y alojamiento; "
                 "no usa precios recordados como ofertas actuales.")
    else:
        st.info("La candidata no se adopta. Se conserva la estrategia anterior.")
    st.write(informe["motivo_validacion"])
    st.caption("Solo describe estas pruebas ficticias. No demuestra que funcione mejor en todos los viajes ni con precios reales.")
    with st.expander("Ver las decisiones y la evidencia"):
        st.json(informe)
    st.download_button("Descargar informe del experimento", json.dumps(informe, ensure_ascii=False, indent=2),
                       file_name="experimento-viajesibi.json", mime="application/json")


def mostrar_aprendizaje():
    st.header("Aprender de la experiencia")
    st.write("Primero busca viajes. Después propone una estrategia basada en lo observado, la prueba "
             "en otras fechas y solo la recuerda si mejora los resultados.")
    st.warning("Laboratorio con ofertas ficticias y Qwen3 real. No consume SerpApi ni modifica las estrategias de búsquedas reales.")
    st.caption("Adaptación sencilla inspirada en Harness²; no ejecuta ese proyecto ni reentrena Qwen3.")
    st.info("Encargo: salir de Valencia · 2 adultos · 3 noches · cultura · 500 € de grupo. "
            "Objetivo: encontrar una opción válida, con un máximo de 3 destinos consultados.")
    with st.expander("Qué se compara y qué cuenta como mejora"):
        st.write("Práctica: 1 y 8 de febrero de 2027. Pruebas reservadas: 15 y 22 de febrero. "
                 "Las respuestas reservadas no se incorporan a la memoria de práctica.")
        st.write("Ambas estrategias usan Qwen3, las mismas ofertas, condiciones y límites. "
                 "La candidata debe encontrar viaje en las dos pruebas, no empeorar coste ni consultas "
                 "y mejorar al menos una medida. En empate se conserva la versión anterior.")
        st.caption("Aprender también tiene coste: dos búsquedas de práctica, una llamada de propuesta y cuatro búsquedas "
                   "de validación. No equivale a ahorro neto desde el primer uso. El catálogo tiene patrones semanales "
                   "repetidos; transferir entre estas fechas no prueba generalización al mercado real.")
    memoria = MemoriaBusquedas()
    st.subheader("1. Acumular experiencia")
    if st.button("Realizar las dos búsquedas de práctica"):
        estado = st.empty()
        with st.spinner("Qwen3 está buscando y registrando resultados…"):
            st.session_state.practica_mejora = practicar(ClienteOllama(), consultar_catalogo_ficticio, memoria, estado.info)
        estado.empty()
    if "practica_mejora" in st.session_state:
        st.table([{"Fecha": r["ida"], "Viaje válido": r["viaje_encontrado"], "Consultas": r["consultas"],
                   "Error": r["error"] or "—"} for r in st.session_state.practica_mejora])
    experiencia = memoria.recordar(CONTEXTO_LAB, PRESUPUESTO_LAB)
    if experiencia:
        st.table([{"Destino": CIUDADES[e["aeropuerto"]], "Fechas observadas": ", ".join(e["fechas_observadas"]),
                   "Observaciones": e["observaciones"], "Media histórica (no oferta)": f"{e['media_historica']:.2f} €"}
                  for e in experiencia])
    else:
        st.caption("Aún no hay resultados repetidos suficientes. Volver a pulsar práctica no duplica las mismas fechas.")
    st.subheader("2. Proponer y probar")
    if st.button("Proponer una mejora y probarla en fechas reservadas", disabled=not experiencia):
        estado = st.empty()
        try:
            with st.spinner("Comparando estrategias con el mismo modelo…"):
                experimentar(ClienteOllama(), consultar_catalogo_ficticio, memoria, estado.info)
        except ErrorOllama as error:
            st.error(str(error))
        finally:
            estado.empty()
    informes = memoria.experimentos(CONTEXTO_LAB)
    if informes:
        indice = st.selectbox("Experimento guardado", range(len(informes)),
                             format_func=lambda i: informes[i]["fecha_utc"] + " · " + ("adoptada" if informes[i]["adoptada"] else "no adoptada"))
        mostrar_informe(informes[indice])
    if memoria.activa(CONTEXTO_LAB):
        st.subheader("4. Usarla en el siguiente viaje")
        st.caption("La política permanece en SQLite al cerrar la app. Se volverán a consultar precios para el 1–4 de marzo de 2027.")
        if st.button("Buscar otro viaje usando la experiencia guardada"):
            with st.spinner("Comprobando el siguiente viaje…"):
                st.session_state.siguiente_mejora = ejecutar_caso(
                    ClienteOllama(), consultar_catalogo_ficticio, (date(2027, 3, 1), date(2027, 3, 4)),
                    memoria.experiencia_validada(CONTEXTO_LAB, PRESUPUESTO_LAB))
        if "siguiente_mejora" in st.session_state:
            r = st.session_state.siguiente_mejora
            st.write(f"Consultas: {r['consultas']} · Viaje válido: {'sí' if r['viaje_encontrado'] else 'no'}")
            if r["total"] is not None:
                st.write(f"Total comprobado para este viaje: {r['total']:.2f} €.")
            for paso in r["traza"]:
                st.write(paso)
            if r["error"]:
                st.error(r["error"])
