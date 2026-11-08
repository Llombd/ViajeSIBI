"""Interfaz local: python3 -m streamlit run app.py --server.address 127.0.0.1."""

import streamlit as st

from src.agent import AgenteViajes, ErrorOllama


EJEMPLOS = (
    ("Escapada cultural", "Compara hasta tres destinos",
     "Somos dos personas, cuatro días desde Madrid, nos gusta la cultura y tenemos "
     "1400 EUR en total. Recomienda hasta tres destinos."),
    ("Coste de Oporto", "Calcula el precio de un destino",
     "Calcula el coste de Oporto para dos personas, cuatro días desde Madrid. "
     "Tenemos 800 EUR en total."),
    ("Viaje en grupo", "Explora opciones para cuatro personas",
     "Somos cuatro personas, viajamos una semana desde Madrid y tenemos "
     "3000 EUR en total. Nos interesa la cultura. ¿Dónde podemos ir?"),
)


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
            <p>Cuéntame cómo quieres viajar y compara destinos con costes del catálogo.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def mostrar_ejemplos():
    st.subheader("Empieza con una idea")
    seleccionado = None
    for columna, (titulo, descripcion, peticion) in zip(st.columns(3), EJEMPLOS):
        with columna, st.container(border=True):
            st.markdown(f"**{titulo}**")
            st.caption(descripcion)
            if st.button(f"Probar · {titulo}", use_container_width=True):
                seleccionado = peticion
    return seleccionado


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
            with st.expander("Herramientas y validaciones"):
                st.code("\n\n".join(mensaje["trazas"]), language=None)


def main():
    st.set_page_config(page_title="ViajeSIBI", page_icon="🧳", layout="wide")
    # Cada pestaña tiene su propio agente; nunca se comparte con otros usuarios.
    if "agente" not in st.session_state:
        st.session_state.agente = AgenteViajes(mostrar=lambda texto: None)
        st.session_state.mensajes = []

    with st.sidebar:
        st.title("🧳 ViajeSIBI")
        st.caption("Agente local · Ollama y Qwen3")
        if st.button("Nueva conversación", use_container_width=True):
            st.session_state.agente = AgenteViajes(mostrar=lambda texto: None)
            st.session_state.mensajes = []
            st.rerun()
        st.subheader("Qué indicar")
        st.caption("- Ciudad de salida\n- Duración del viaje\n- Número de viajeros\n- Presupuesto total y moneda")
        st.caption("Puedes añadir región e intereses. El catálogo permite estimar el transporte desde Madrid.")

    mostrar_cabecera()
    st.caption("Demostración universitaria · 15 destinos · Datos ficticios del catálogo")
    ejemplo = mostrar_ejemplos() if not st.session_state.mensajes else None

    for mensaje in st.session_state.mensajes:
        mostrar_mensaje(mensaje)

    texto = st.chat_input("Cuéntame tu viaje…") or ejemplo
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
