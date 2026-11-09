"""Interfaz local: python3 -m streamlit run app.py --server.address 127.0.0.1."""

from copy import deepcopy
from uuid import uuid4

import streamlit as st

from src.agent import AgenteViajes, ErrorOllama
from src.datos_viaje import DatosViaje
from src.plan_colaborativo import AgentePreferenciasViaje, PREFERENCIAS, RUTAS, coordinar
from src.tools import buscar_destinos


def mostrar_cabecera():
    st.markdown(
        """
        <style>
        .viaje-cabecera {
            padding: clamp(1.25rem, 4vw, 2.75rem);
            margin-bottom: 1.4rem;
            border-radius: 1.35rem;
            background: linear-gradient(120deg, #102e39, #14574f);
            color: #f6fffb;
        }
        .viaje-cabecera h1 {
            color: inherit;
            font-size: clamp(2rem, 5vw, 3.1rem);
            letter-spacing: -.045em;
            line-height: 1.1;
            padding: .35rem 0 .55rem;
        }
        .viaje-cabecera p { color: #e3f5ee; margin: 0; max-width: 36rem; }
        .stChatMessage .stText { white-space: pre-wrap; overflow-wrap: anywhere; }
        .viaje-cabecera .viaje-etiqueta {
            color: #aee7d2;
            font-size: .78rem;
            font-weight: 700;
            letter-spacing: .12em;
            text-transform: uppercase;
        }
        </style>
        <section class="viaje-cabecera" aria-labelledby="viaje-titulo">
            <p class="viaje-etiqueta">Tu asistente de viajes</p>
            <h1 id="viaje-titulo">¿Dónde será tu próximo viaje?</h1>
            <p>Escribe tu consulta abajo. Puedes comparar destinos, consultar un coste o seguir afinando tu viaje en el chat.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def mostrar_mensaje(mensaje):
    with st.chat_message(mensaje["role"]):
        if mensaje.get("error"):
            st.error(mensaje["content"])
        elif mensaje["role"] == "user":
            st.text(mensaje["content"])
        else:
            contenido = mensaje["content"]
            if contenido.startswith("Datos del viaje\n"):
                resumen, _, resultados = contenido.partition("\n\n")
                titulo, _, datos = resumen.partition("\n")
                st.markdown(f"### {titulo}\n\n" + datos.replace("\n", "  \n"))
                if resultados:
                    titulo, _, detalle = resultados.partition("\n")
                    st.markdown(f"### {titulo.rstrip(':')}\n\n{detalle}")
            else:
                st.markdown(contenido)
        if mensaje.get("trazas"):
            trazas = mensaje["trazas"]
            consultas = [linea for linea in trazas if linea.startswith("[Herramienta]")]
            busquedas = sum(linea.startswith("[Herramienta] buscar_destinos(") for linea in consultas)
            costes = sum(linea.startswith("[Herramienta] estimar_coste(") for linea in consultas)
            orden = next((linea.split(": ", 1)[1] for linea in reversed(trazas)
                          if linea.startswith("[Agente de preferencias] Orden de candidatos: ")), None)
            st.caption("**Cómo se preparó la respuesta**")
            st.caption(f"El planificador solicitó {busquedas} búsquedas de destinos y "
                       f"{costes} cálculos de coste simulado.")
            if orden:
                st.caption("Primeros candidatos tras aplicar tus valoraciones · "
                           + ", ".join(orden.split(", ")[:3]))
            with st.expander("Herramientas y validaciones"):
                st.code("\n\n".join(trazas), language=None)


def gestionar_conversaciones():
    estado = st.session_state
    if st.button("Nueva conversación", use_container_width=True):
        estado.agente = AgenteViajes(mostrar=lambda texto: None, datos=estado.repositorio_viaje)
        estado.mensajes = []
        estado.conversacion_activa = None
        st.rerun()

    st.subheader("Conversaciones guardadas")
    guardadas = estado.conversaciones_guardadas
    if st.button("Guardar conversación", disabled=not estado.mensajes, use_container_width=True):
        titulo = " ".join(estado.mensajes[0]["content"].split())
        copia = (titulo, deepcopy(estado.agente), deepcopy(estado.mensajes))
        if estado.conversacion_activa is None:
            estado.conversacion_activa = len(guardadas)
            guardadas.append(copia)
        else:
            guardadas[estado.conversacion_activa] = copia
        st.success("Conversación guardada.")

    if guardadas:
        seleccion = st.selectbox(
            "Selecciona una conversación",
            range(len(guardadas)),
            format_func=lambda indice: f"{indice + 1}. {guardadas[indice][0][:60]}",
        )
        if st.button("Abrir conversación", use_container_width=True):
            _, estado.agente, estado.mensajes = deepcopy(guardadas[seleccion])
            estado.conversacion_activa = seleccion
            st.rerun()
    st.caption("Las conversaciones se guardan durante esta sesión. Guarda el chat actual antes de cambiar si quieres conservarlo. Al recargar o cerrar la pestaña se perderán.")


def formulario_viaje():
    with st.expander("Introducir los datos en un formulario"):
        with st.form("datos_viaje"):
            origen = st.text_input("Ciudad de salida")
            izquierda, derecha = st.columns(2)
            with izquierda:
                dias = st.number_input("Duración en días", min_value=1, value=4, step=1)
            with derecha:
                viajeros = st.number_input("Número de viajeros", min_value=1, value=2, step=1)
            presupuesto = st.number_input("Presupuesto total en euros", min_value=0.0, step=50.0, format="%.2f")
            region = st.text_input("Región (opcional)")
            intereses = st.text_input("Intereses (opcional)")
            enviar = st.form_submit_button("Enviar al chat", type="primary")

        if enviar:
            if not origen.strip() or round(presupuesto, 2) <= 0:
                st.warning("Indica la ciudad de salida y un presupuesto mayor que cero.")
                return None
            importe = f"{presupuesto:.2f}".rstrip("0").rstrip(".").replace(".", ",")
            consulta = (
                f"Busco un viaje de {dias} días desde {origen.strip()} para {viajeros} personas. "
                f"Mi presupuesto total es de {importe} EUR."
            )
            if region.strip():
                consulta += f" Prefiero la región {region.strip()}."
            if intereses.strip():
                consulta += f" Me interesa: {intereses.strip()}."
            return consulta + " ¿Qué destinos me recomiendas?"
    return None


def mostrar_preferencias(datos):
    with st.expander("Preferencias aprendidas"):
        st.caption("Las valoraciones de este perfil local se guardan para ordenar futuras búsquedas.")
        destinos = {d["id"]: d["nombre"] for d in buscar_destinos()["destinos"]}
        destino = st.selectbox("Destino que quieres valorar", list(destinos), format_func=destinos.__getitem__)
        izquierda, derecha = st.columns(2)
        if izquierda.button("Me interesa"):
            datos.valorar(destino, 1)
        if derecha.button("Me interesa menos"):
            datos.valorar(destino, -1)
        votos = datos.valoraciones()
        if votos:
            for clave, voto in votos.items():
                etiqueta = "Me interesa" if voto > 0 else "Me interesa menos"
                st.write(f"{destinos.get(clave, clave)} · {etiqueta}")
        else:
            st.caption("Todavía no hay valoraciones.")


def demostrar_coordinacion(datos):
    st.subheader("Demostración de agentes")
    st.caption("Escenario simulado para una persona y dos noches. Las ofertas, los horarios y los importes son datos de prueba.")
    memoria = AgentePreferenciasViaje(datos.ruta)
    perfil = memoria.perfil()
    if perfil:
        st.write("Preferencias guardadas", {
            PREFERENCIAS[clave]: cantidad for clave, cantidad in perfil.items()
        })
    with st.form("demo_coordinacion"):
        origen = st.selectbox("Ciudad de salida de la demo", list(RUTAS))
        presupuesto = st.number_input("Límite para transporte y alojamiento (€)", min_value=1, value=250)
        permitir_tarde = st.checkbox("En este viaje sí puedo llegar después de las 22:00")
        ejecutar = st.form_submit_button("Comparar plan sin memoria y plan personalizado")
    estado = st.session_state
    if ejecutar:
        inicial, _ = coordinar(origen, presupuesto, {}, permitir_tarde)
        plan, pasos = coordinar(origen, presupuesto, perfil, permitir_tarde)
        estado.demo_plan = {
            "id": uuid4().hex, "origen": origen, "presupuesto": presupuesto,
            "permitir_tarde": permitir_tarde, "perfil": perfil, "inicial": inicial,
            "plan": plan, "pasos": pasos, "reparado": False,
        }
    if "demo_plan" not in estado:
        return
    demo = estado.demo_plan
    plan = demo["plan"]
    if plan and not demo["reparado"] and st.button("Simular cancelación del transporte"):
        plan, pasos = coordinar(demo["origen"], demo["presupuesto"], demo["perfil"],
                                demo["permitir_tarde"], cancelado=plan)
        demo.update(plan=plan, pasos=pasos, reparado=True)
    columnas = st.columns(2)
    for columna, titulo, opcion in zip(columnas, ("Sin memoria", "Con memoria"), (demo["inicial"], plan)):
        with columna:
            st.markdown(f"**{titulo}**")
            if opcion:
                st.write(f"{opcion.ciudad} · {opcion.total} €")
                st.write(f"{opcion.transporte.nombre} · llegada a las {opcion.transporte.llegada:02d}:00")
                st.write(opcion.alojamiento.nombre)
            else:
                st.write("Sin combinación dentro del presupuesto.")
    if plan:
        for clave, etiqueta in PREFERENCIAS.items():
            if st.button(etiqueta, key=f"correccion_{clave}"):
                memoria.aprender(demo["id"], clave)
                st.success("Corrección guardada. Vuelve a comparar para ver su efecto.")
    st.markdown("**Decisiones de los agentes**")
    for paso in demo["pasos"]:
        st.text(paso)


def main():
    st.set_page_config(page_title="ViajeSIBI", page_icon="🧳", layout="wide")
    # Cada pestaña tiene su propio agente; nunca se comparte con otros usuarios.
    if "repositorio_viaje" not in st.session_state:
        st.session_state.repositorio_viaje = DatosViaje()
    if "agente" not in st.session_state:
        st.session_state.agente = AgenteViajes(mostrar=lambda texto: None, datos=st.session_state.repositorio_viaje)
        st.session_state.mensajes = []
    st.session_state.setdefault("conversaciones_guardadas", [])
    st.session_state.setdefault("conversacion_activa", None)

    with st.sidebar:
        st.title("🧳 ViajeSIBI")
        st.caption("Agente local · Ollama y Qwen3")
        gestionar_conversaciones()

    mostrar_cabecera()
    with st.expander("Probar coordinación y aprendizaje", expanded=True):
        demostrar_coordinacion(st.session_state.repositorio_viaje)
    st.info("ViajeSIBI propone destinos y calcula costes simulados. Para ver ofertas y disponibilidad, abre un buscador externo.")
    vuelos, trenes, alojamientos = st.columns(3)
    vuelos.link_button("Buscar vuelos", "https://www.google.com/travel/flights?hl=es")
    trenes.link_button("Buscar trenes", "https://www.renfe.com/es/es")
    alojamientos.link_button("Buscar alojamiento", "https://www.booking.com/index.es.html")
    mostrar_preferencias(st.session_state.repositorio_viaje)
    with st.container(border=True):
        st.subheader("Qué indicar en tu consulta")
        st.markdown("**Ciudad de salida** · **Duración** · **Número de viajeros** · **Presupuesto total y moneda**")
        st.caption("Región e intereses son opcionales. El catálogo permite estimar el transporte desde Madrid.")

    consulta_formulario = formulario_viaje()
    for mensaje in st.session_state.mensajes:
        mostrar_mensaje(mensaje)

    texto = st.chat_input("Escribe aquí qué viaje tienes en mente…") or consulta_formulario
    if texto and texto.strip():
        usuario = {"role": "user", "content": texto}
        st.session_state.mensajes.append(usuario)
        mostrar_mensaje(usuario)
        trazas = []
        agente = st.session_state.agente
        agente.mostrar = trazas.append
        try:
            with st.spinner("Consultando al agente local; puede tardar unos minutos…"):
                respuesta = agente.responder(texto)
            mensaje = {"role": "assistant", "content": respuesta, "trazas": trazas}
        except ErrorOllama as error:
            # El agente restaura su historial si falla Ollama. El aviso queda
            # visible, pero no se convierte en una respuesta del modelo.
            mensaje = {"role": "assistant", "content": str(error), "error": True, "trazas": trazas}
        finally:
            agente.mostrar = lambda texto: None
        st.session_state.mensajes.append(mensaje)
        st.rerun()


if __name__ == "__main__":
    main()
