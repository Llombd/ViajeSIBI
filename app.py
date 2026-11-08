"""Interfaz local: python3 -m streamlit run app.py --server.address 127.0.0.1."""

import streamlit as st

from src.agent import AgenteViajes, ErrorOllama


def mostrar_mensaje(mensaje):
    with st.chat_message(mensaje["role"]):
        if mensaje.get("error"):
            st.error(mensaje["content"])
        else:
            st.markdown(mensaje["content"])
        if mensaje.get("trazas"):
            with st.expander("Herramientas y validaciones"):
                st.code("\n\n".join(mensaje["trazas"]), language=None)


def main():
    st.set_page_config(page_title="ViajeSIBI", page_icon="🧳", layout="wide")
    st.title("🧳 ViajeSIBI")
    st.caption("Tu agente de viajes · Ollama local · Qwen3")
    st.info("Demostración universitaria: los 15 destinos utilizan costes y características ficticios. No son ofertas reales.")

    # Cada pestaña tiene su propio agente; nunca se comparte con otros usuarios.
    if "agente" not in st.session_state:
        st.session_state.agente = AgenteViajes(mostrar=lambda texto: None)
        st.session_state.mensajes = []

    if st.button("Nueva conversación"):
        st.session_state.agente = AgenteViajes(mostrar=lambda texto: None)
        st.session_state.mensajes = []
        st.rerun()

    st.caption("Indica origen, días, viajeros y presupuesto total. Región e intereses son opcionales. La conversación dura esta sesión.")
    if not st.session_state.mensajes:
        st.markdown("Por ejemplo: *Somos dos personas, cuatro días desde Madrid, nos gusta la cultura y tenemos 1400 EUR en total. Recomienda hasta tres destinos.*")

    for mensaje in st.session_state.mensajes:
        mostrar_mensaje(mensaje)

    texto = st.chat_input("¿Qué viaje tienes en mente?")
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
        mostrar_mensaje(mensaje)


if __name__ == "__main__":
    main()
