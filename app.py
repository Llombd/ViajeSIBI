"""Pantalla principal de ViajeSIBI para planificar con ofertas reales."""

import streamlit as st

from src.interfaz_ofertas import mostrar_ofertas


if __name__ == "__main__":
    st.set_page_config(page_title="ViajeSIBI · Planificar viaje", page_icon="🧳", layout="wide")
    mostrar_ofertas()
