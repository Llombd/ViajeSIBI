"""Vista local para buscar y comparar ofertas reales."""

from datetime import date, timedelta
import os
import re
from urllib.parse import urlencode

import streamlit as st

from src.agent import ClienteOllama, ErrorOllama
from src.datos_viaje import DatosViaje
from src.ofertas_reales import ErrorOfertas, consultar_serpapi
from src.seleccion_viaje import CIUDADES, intervalos, planificar_con_alternativas


def guardar_clave_sesion():
    st.session_state.clave_serpapi = st.session_state.campo_serpapi


def mostrar_ofertas():
    st.title("🧳 Planificar viaje")
    st.caption("Dinos de dónde sales y qué te apetece. El agente elige destinos y consulta ofertas reales de vuelo y alojamiento.")
    clave = os.getenv("SERPAPI_API_KEY")
    if not clave:
        st.session_state.setdefault("campo_serpapi", st.session_state.get("clave_serpapi", ""))
        clave = st.text_input("Clave de SerpApi", type="password", key="campo_serpapi", on_change=guardar_clave_sesion)
        st.caption("La clave dura esta sesión. Para conservarla, configura SERPAPI_API_KEY al iniciar la app.")
    hoy = date.today()
    modo = st.radio("¿Cuándo quieres viajar?", (
        "Me da igual", "Tengo un mes aproximado", "Tengo un intervalo flexible", "Tengo fechas exactas",
    ))
    st.caption("Con fechas exactas, las alternativas mantienen esos días. Con un mes o intervalo flexible, "
               "el agente puede probar otros días dentro del periodo indicado.")
    if "perfil_ofertas" not in st.session_state:
        st.session_state.perfil_ofertas = DatosViaje().prioridades_ofertas()
    perfil = st.session_state.perfil_ofertas
    st.subheader("Qué buscas en el destino")
    guardados = ", ".join(filter(None, (perfil.get("imprescindibles"), perfil.get("gustos"))))
    texto_gustos = st.text_input("Gustos (opcional)", value=guardados, max_chars=500,
                                placeholder="Por ejemplo, buenas playas, museos, vida nocturna")
    gustos = list(dict.fromkeys(parte.strip() for parte in re.split(r"[,;]", texto_gustos) if parte.strip()))
    protegidos = {parte.strip() for parte in perfil.get("imprescindibles", "").split(",")}
    conservar = st.multiselect("¿Cuáles quieres conservar?", gustos,
                               default=[gusto for gusto in gustos if gusto in protegidos])
    st.caption("Separa los gustos con comas. Los que marques se conservan al buscar alternativas. Si no hay un plan viable, el agente puede dejar de tener en cuenta los que dejes sin marcar, empezando por el último.")
    imprescindibles = ", ".join(conservar)
    preferencias = ", ".join(gusto for gusto in gustos if gusto not in conservar)
    with st.form("buscar_ofertas"):
        st.subheader("Salida y fechas")
        origen = st.selectbox("¿Desde dónde sales?", list(CIUDADES), index=list(CIUDADES).index(perfil["origen"]) if perfil.get("origen") in CIUDADES else None,
                              format_func=CIUDADES.__getitem__)
        origen_fijo = st.checkbox("Solo quiero salir desde este aeropuerto", value=perfil.get("origen_fijo", False))
        st.caption("Si dejas esta opción desmarcada, se pueden probar aeropuertos alternativos cuando estén disponibles.")
        primera, segunda = st.columns(2)
        ida, vuelta = hoy + timedelta(days=7), hoy + timedelta(days=60)
        if modo == "Tengo fechas exactas":
            ida = primera.date_input("Ida", value=hoy + timedelta(days=30), min_value=hoy)
            vuelta = segunda.date_input("Vuelta", value=hoy + timedelta(days=33), min_value=hoy)
        elif modo == "Tengo un intervalo flexible":
            ida = primera.date_input("Primera salida posible", value=ida, min_value=hoy)
            vuelta = segunda.date_input("Último día para volver", value=vuelta, min_value=hoy)
        elif modo == "Tengo un mes aproximado":
            indice_mes = hoy.year * 12 + hoy.month - 1
            meses = [
                date(indice // 12, indice % 12 + 1, 1)
                for indice in range(indice_mes, indice_mes + 12)
            ]
            mes = st.selectbox("Mes aproximado", meses, format_func=lambda fecha: fecha.strftime("%m/%Y"))
            ida = max(hoy, mes)
            vuelta = (mes.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        else:
            st.caption("Buscaremos viajes entre la semana que viene y los próximos 60 días.")
        noches = (vuelta - ida).days if modo == "Tengo fechas exactas" else st.number_input(
            "Noches", min_value=1, max_value=30, value=3,
        )
        st.subheader("Viajeros y presupuesto")
        grupo, dinero = st.columns(2)
        adultos = grupo.number_input("Adultos", min_value=1, max_value=9, value=2)
        presupuesto = dinero.number_input("Presupuesto del grupo para vuelo y alojamiento (€)", min_value=1, value=800)
        margen_persona = st.number_input("¿Cuánto más considerarías pagar por persona? (€)", min_value=0, max_value=100,
                                         value=perfil.get("margen_persona", 50))
        st.caption("Si una opción encaja en este margen, el agente la muestra antes de cambiar el aeropuerto o los gustos. Pon 0 para buscar primero dentro del presupuesto. Si al final solo hay opciones más caras, se muestran aparte. Tope del margen: 100 € por grupo.")

        guardar = st.checkbox("Recordar mi aeropuerto y prioridades para próximos viajes")
        buscar = st.form_submit_button("Encontrar opciones")
    if buscar:
        st.session_state.pop("resultado_prioridades", None)
        if not clave.strip():
            st.warning("Introduce tu clave de SerpApi para empezar.")
            return
        fechas = intervalos(ida, vuelta, noches) if noches > 0 else []
        if not origen or not fechas:
            st.warning("Indica desde dónde sales y elige fechas que permitan las noches del viaje.")
            return
        if guardar:
            perfil_actualizado = dict(origen=origen, gustos=preferencias, origen_fijo=origen_fijo,
                                     imprescindibles=imprescindibles, margen_persona=margen_persona)
            DatosViaje().guardar_prioridades_ofertas(perfil_actualizado)
            st.session_state.perfil_ofertas = perfil_actualizado
        margen = min(margen_persona * adultos, 100)
        try:
            with st.spinner("Eligiendo destinos y comprobando vuelos y alojamientos…"):
                planes, registro, primer_total = planificar_con_alternativas(
                    ClienteOllama(), lambda parametros: consultar_serpapi(clave.strip(), parametros),
                    origen, fechas, preferencias, adultos, presupuesto,
                    margen=margen, origen_fijo=origen_fijo, imprescindibles=imprescindibles,
                )
        except (ErrorOfertas, ErrorOllama) as error:
            st.error(str(error))
            return
        st.session_state.resultado_prioridades = planes, registro, primer_total, presupuesto, origen, adultos, margen
    if "resultado_prioridades" not in st.session_state:
        return
    planes, registro, primer_total, limite, salida, personas, margen = st.session_state.resultado_prioridades
    st.subheader(f"Opciones desde {CIUDADES[salida]}")
    st.caption(f"{personas} adultos · límite {limite} €")
    provisionales = [plan for plan in planes if not plan.get("impuestos_confirmados", True)]
    planes = [plan for plan in planes if plan.get("impuestos_confirmados", True)]
    validos = [plan for plan in planes if plan["total"] <= limite]
    if validos and not any(plan.get("salida", salida) == salida and not plan.get("preferencias_omitidas")
                           for plan in validos):
        st.info("No encontramos un plan viable con las condiciones iniciales. Estas alternativas indican qué se cambió.")
    if not validos and planes:
        coste = planes[0]["total"]
        if coste <= limite + margen:
            st.info("Encontramos una alternativa dentro del margen que indicaste. Puedes decidir si aceptas el aumento.")
        st.warning(f"La opción comprobada más barata cuesta {coste:.2f} €, "
                   f"{coste - limite:.2f} € por encima del presupuesto. "
                   "¿Quieres cambiar el presupuesto o probar otras fechas? Puedes hacerlo en el formulario.")
        st.markdown("**Alternativas comprobadas fuera de presupuesto**")
    elif not validos and not provisionales:
        st.info("No se pudo comprobar un precio completo en las rutas y fechas consultadas. "
                "Subir el presupuesto no resuelve por sí solo la falta de ofertas.")
        if salida == "LEN":
            st.caption("¿Te serviría salir desde Valladolid o Madrid? Puedes elegir otro aeropuerto en el formulario. "
                       "El precio mostrado no incluye el traslado desde León.")
        else:
            st.caption("¿Puedes ampliar las fechas o salir desde otro aeropuerto? Puedes ajustar el formulario.")
    for plan in (validos or planes)[:3]:
        mostrar_plan(plan, salida, personas, limite)
    if not validos and provisionales:
        st.markdown("**Alternativas con impuestos pendientes de confirmar**")
        for plan in provisionales[:3]:
            mostrar_plan(plan, salida, personas, limite)
    st.caption("Precios de la consulta. Comprueba la disponibilidad y el importe final antes de reservar. "
               "El presupuesto comparado cubre solo vuelo y alojamiento.")
    with st.expander("Qué aportó revisar alternativas", expanded=True):
        st.caption("Comparamos detener la búsqueda tras la primera propuesta de Qwen3 con revisar "
                   "todas las propuestas consultadas en este viaje.")
        if not validos:
            st.write("Ninguna de las propuestas consultadas dio un plan dentro del presupuesto.")
        elif primer_total is None or primer_total > limite:
            st.write(f"La primera propuesta no dio un plan válido. Al seguir buscando, "
                     f"encontramos {len(validos)} opciones dentro del presupuesto.")
        elif primer_total > planes[0]["total"]:
            ahorro = primer_total - planes[0]["total"]
            st.write(f"La mejor alternativa comprobada cuesta {ahorro:.2f} € menos que "
                     f"la primera propuesta ({primer_total:.2f} €).")
        else:
            st.write("La primera propuesta ya era la más económica entre las consultadas.")
    with st.expander("Qué se consultó y cómo se eligieron las combinaciones", expanded=not validos):
        for paso in registro:
            st.write(paso)



def mostrar_plan(plan, salida, personas, limite):
    ida, vuelta = plan["ida_fecha"], plan["vuelta_fecha"]
    salida_real = plan.get("salida", salida)
    impuestos = plan.get("impuestos_confirmados", True)
    st.subheader(f"{plan['ciudad']} · {plan['total']:.2f} €")
    if salida_real != salida:
        st.info(f"Salida alternativa: {CIUDADES[salida_real]}. El traslado desde {CIUDADES[salida]} queda fuera del precio.")
    if plan.get("preferencias_omitidas"):
        st.caption("Preferencias flexibilizadas: " + ", ".join(plan["preferencias_omitidas"]))
    st.write(f"{ida:%d/%m/%Y} a {vuelta:%d/%m/%Y} · {plan['nombre']}")
    if not impuestos:
        st.caption("Total según las tarifas publicadas. Impuestos de la estancia pendientes de confirmar.")
    elif plan["total"] > limite:
        st.caption(f"{plan['total'] - limite:.2f} € por encima de tu límite.")
    st.write(f"Vuelos del grupo: {plan['vuelo']:.2f} € · Estancia: {plan['alojamiento']:.2f} €")
    numeros = []
    for etiqueta, tramos in (("Ida", plan["ida"]), ("Vuelta", plan["vuelta"])):
        st.markdown(f"**{etiqueta}**")
        for tramo in tramos:
            partida = tramo.get("departure_airport", {})
            llegada = tramo.get("arrival_airport", {})
            numero = tramo.get("flight_number", "")
            numeros.append(numero)
            st.text(f"{tramo.get('airline', '')} {numero} · {partida.get('id', '')} {partida.get('time', '')}"
                    f" → {llegada.get('id', '')} {llegada.get('time', '')}")
    vuelo, estancia = st.columns(2)
    fechas = f"{ida.isoformat()} a {vuelta.isoformat()}"
    consulta_vuelo = f"vuelos {salida_real} {plan['ciudad']} {fechas} {personas} adultos {' '.join(numeros)}"
    consulta_hotel = f"{plan['nombre']} {plan['ciudad']} {fechas} {personas} adultos"
    vuelo.link_button("Comprobar vuelo", "https://www.google.com/travel/flights?" + urlencode({"q": consulta_vuelo}))
    estancia.link_button("Comprobar alojamiento", "https://www.google.com/travel/hotels?" + urlencode({"q": consulta_hotel}))
    st.caption("Los enlaces abren una búsqueda con los datos del plan. El precio puede cambiar.")
