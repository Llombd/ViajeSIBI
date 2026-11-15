"""Vista local para buscar y comparar ofertas reales."""

from collections import Counter
from datetime import date, timedelta
import os
import re
from urllib.parse import urlencode
from uuid import uuid4

import streamlit as st

from src.agent import ClienteOllama, ErrorOllama
from src.comparar_equipo import comparar_un_agente_y_equipo
from src.balance_comparacion import balance_comparacion
from src.interfaz_aprendizaje import mostrar_aprendizaje
from src.interfaz_evidencia import mostrar_evidencia
from src.memoria_busquedas import MemoriaBusquedas, contexto_viaje
from src.datos_viaje import DatosViaje
from src.demo_ofertas import consultar_catalogo_ficticio
from src.ofertas_reales import ErrorOfertas, TIPOS_ALOJAMIENTO, consultar_con_filtros, consultar_serpapi
from src.seleccion_viaje import diagnosticar, CIUDADES, comparar_estrategias, evaluar_comparacion, intervalos, planificar_con_alternativas


def guardar_clave_sesion():
    st.session_state.clave_serpapi = st.session_state.campo_serpapi


def mostrar_ofertas():
    st.title("🧳 Planificar viaje")
    st.caption("Un equipo de agentes busca destinos, vuelos y alojamiento según tus condiciones.")
    with st.expander("Cómo trabaja el equipo"):
        st.write("Coordinación reparte el trabajo. Destinos propone ciudades y fechas. "
                 "Transporte comprueba vuelos. Alojamiento compara estancias con los vuelos observados. "
                 "Cada rol usa Qwen3 con instrucciones e historial propios. "
                 "El coordinador puede volver a vuelos o estancias del mismo destino, cambiar fechas permitidas o pedir otra ciudad. Se compara siempre el total y las decisiones aparecen en la traza.")
        st.caption("La comparación y el laboratorio conservan su protocolo anterior de un planificador, "
                   "para que sus resultados sigan siendo interpretables.")
    planificar, comparacion, demos, aprendizaje = st.tabs(
        ("Planificar viaje", "Comparar IA y agente", "Demostraciones", "Aprendizaje"),
        key="apartado_viajesibi", on_change="rerun",
    )
    if planificar.open:
        with planificar:
            mostrar_formulario()
    elif comparacion.open:
        with comparacion:
            st.info("Mismo Qwen3 y las mismas ofertas. Compara un agente con herramientas frente al equipo de cuatro agentes.")
            st.caption("Esta comparación mide el valor de revisar la búsqueda. No demuestra superioridad frente a todas las IA o buscadores.")
            mostrar_formulario(comparar=True)
    elif aprendizaje.open:
        with aprendizaje:
            mostrar_aprendizaje()
    elif demos.open:
        with demos:
            with st.expander("Cómo explicar el proyecto sin ver el código"):
                st.write("El encargo es encontrar un viaje con un presupuesto y unas prioridades. "
                         "El destino lo propone Qwen3; los precios los comprueban las herramientas.")
                st.write("Después de cada consulta, el agente puede revisar el destino o las fechas. "
                         "Se ve qué dato recibió, qué decidió comprobar y qué resultado obtuvo.")
                st.write("La utilidad se mide por viajes conseguidos dentro del presupuesto, coste de esos viajes "
                         "y consultas necesarias. Un cambio de destino por sí solo no demuestra una mejora.")
                st.caption("La comparación controla las condiciones: mismo modelo, datos, filtros y máximo de intentos. "
                           "Una IA con herramientas también puede funcionar como agente. No se compara contra todas las IA del mercado.")
            modo = st.radio("Qué quieres mostrar",
                            ("Búsquedas guardadas", "Comparaciones guardadas", "Búsqueda simulada", "Comparación simulada", "Defender el proyecto"), horizontal=True)
            if modo == "Defender el proyecto":
                mostrar_evidencia()
            elif modo in ("Búsqueda simulada", "Comparación simulada"):
                st.warning("Qwen3 planifica con vuelos, alojamientos y precios ficticios, sin usar SerpApi.")
                mostrar_formulario(simulada=True, comparar=modo == "Comparación simulada")
            else:
                mostrar_demostraciones(modo)


def mostrar_formulario(simulada=False, comparar=False):
    comparar_equipo = comparar and st.radio(
        "Qué métodos comparar", ("Un agente y equipo de cuatro", "Lista fija y planificador anterior"),
        horizontal=True,
    ) == "Un agente y equipo de cuatro"
    clave = os.getenv("SERPAPI_API_KEY")
    if not simulada and not clave:
        with st.container(border=True):
            st.subheader("Conexión con SerpApi")
            st.session_state.setdefault("campo_serpapi", st.session_state.get("clave_serpapi", ""))
            clave = st.text_input("Clave de SerpApi", type="password", key="campo_serpapi", on_change=guardar_clave_sesion)
            st.caption("La clave dura esta sesión. Para conservarla, configura SERPAPI_API_KEY al iniciar la app.")
    if "perfil_ofertas" not in st.session_state:
        st.session_state.perfil_ofertas = DatosViaje().prioridades_ofertas()
    perfil = st.session_state.perfil_ofertas
    st.session_state.setdefault("fijar_salida", perfil.get("origen_fijo", False))
    with st.container(border=True):
        st.subheader("Aeropuerto de salida")
        origen = st.selectbox("¿Desde dónde sales?", list(CIUDADES), index=list(CIUDADES).index(perfil["origen"]) if perfil.get("origen") in CIUDADES else None,
                              format_func=CIUDADES.__getitem__)
        origen_fijo = st.checkbox("Solo quiero salir desde este aeropuerto",
                                  key="fijar_salida", disabled=comparar)
        st.caption("En la comparación, ambos métodos mantienen este aeropuerto." if comparar else
                   "Si dejas esta opción desmarcada, se pueden probar aeropuertos alternativos cuando estén disponibles.")

    with st.container(border=True):
        st.subheader("Fechas del viaje")
        hoy = date.today()
        modo = st.radio("¿Cuándo quieres viajar?", (
            "Me da igual", "Tengo un mes aproximado", "Tengo un intervalo flexible", "Tengo fechas exactas",
        ))
        st.caption("Con fechas exactas, las alternativas mantienen esos días. Con un mes o intervalo flexible, "
                   "el agente puede probar otros días dentro del periodo indicado.")
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

    with st.container(border=True):
        st.subheader("Viajeros y presupuesto")
        grupo, dinero = st.columns(2)
        adultos = grupo.number_input("Adultos", min_value=1, max_value=9, value=2)
        presupuesto_persona = dinero.number_input("Presupuesto por persona para vuelo y alojamiento (€)",
                                                  min_value=1, value=400)
        presupuesto = presupuesto_persona * adultos
        margen_persona = st.number_input("¿Cuánto más considerarías pagar por persona? (€)", min_value=0, max_value=100,
                                         value=perfil.get("margen_persona", 50), disabled=comparar)
        margen = 0 if comparar else min(margen_persona * adultos, 100)
        if comparar:
            st.caption(f"Límite de ambos métodos: {presupuesto} € de grupo. En esta comparación no se añade margen.")
        else:
            st.caption(f"Presupuesto del grupo: {presupuesto} €. Máximo con el margen: {presupuesto + margen} € "
                       f"({(presupuesto + margen) / adultos:.2f} € por persona). El margen total se limita a 100 €.")

    with st.container(border=True):
        st.subheader("Gustos y prioridades")
        guardados = ", ".join(filter(None, (perfil.get("imprescindibles"), perfil.get("gustos"))))
        texto_gustos = st.text_input("Gustos (opcional)", value=guardados, max_chars=500,
                                    placeholder="Por ejemplo, buenas playas, museos, vida nocturna")
        gustos = list(dict.fromkeys(parte.strip() for parte in re.split(r"[,;]", texto_gustos) if parte.strip()))
        protegidos = {parte.strip() for parte in perfil.get("imprescindibles", "").split(",")}
        conservar = st.multiselect("¿Cuáles quieres conservar?", gustos,
                                   default=[gusto for gusto in gustos if gusto in protegidos])
        st.caption("Separa los gustos con comas. Los que marques se conservan al buscar alternativas. Si no hay un plan viable, el agente puede dejar de tener en cuenta los que dejes sin marcar, empezando por el último.")
        st.caption("Los gustos orientan a Qwen3. La API comprueba vuelos y alojamientos; no verifica que una ciudad tenga buena comida, playa u otros gustos. Revisa esa adecuación antes de elegir.")
        imprescindibles = ", ".join(conservar)
        preferencias = ", ".join(gusto for gusto in gustos if gusto not in conservar)
        guardar = not (simulada or comparar) and st.checkbox("Recordar mi aeropuerto y prioridades para próximos viajes")
    with st.container(border=True):
        st.subheader("Alojamiento")
        modo_tipos = st.radio("Cómo filtrar los tipos", ("Incluir", "Excluir"), horizontal=True)
        seleccion = st.multiselect("Tipos de alojamiento", list(TIPOS_ALOJAMIENTO),
                                   help="Deja la lista vacía para buscar sin filtrar por tipo.")
        nota_minima = st.selectbox("Valoración mínima de huéspedes", [0, 3, 3.5, 4, 4.5, 5],
                                   format_func=lambda nota: f"{nota:g} de 5" if nota else "Sin mínimo")
    objetivo_opciones = 3 if comparar else st.number_input(
        "Opciones válidas que quieres comprobar", min_value=1, max_value=3, value=3,
        help="Con una opción, la búsqueda se detiene al encontrar un viaje dentro del presupuesto base.")
    tipos = None
    if seleccion:
        tipos = [codigo for nombre, codigo in TIPOS_ALOJAMIENTO.items()
                 if (nombre in seleccion) == (modo_tipos == "Incluir")]
    experiencia_aprendida = []
    if simulada and not comparar and origen and objetivo_opciones == 1:
        memoria = MemoriaBusquedas()
        contexto = contexto_viaje(origen, adultos, noches, texto_gustos, tipos=tipos, nota=nota_minima)
        if memoria.activa(contexto) and st.checkbox("Usar la estrategia validada en el laboratorio", value=True):
            experiencia_aprendida = memoria.experiencia_validada(contexto, presupuesto)
            st.caption("La experiencia guía el orden de candidatos. Se consultarán precios de nuevo; "
                       "la validación previa no garantiza este viaje.")
    if comparar:
        st.caption("Ambos métodos respetan origen, fechas, presupuesto base y filtros. "
                   "Cada uno dispone de hasta 12 consultas de datos y tres combinaciones de destino y fechas. "
                   "El equipo añade decisiones de coordinación; se cuentan todas.")
    buscar = st.button("Comparar estrategias" if comparar else "Encontrar opciones", type="primary")
    resultado_clave = (
        ("comparacion_simulada" if simulada else "comparacion_real")
        if comparar else ("resultado_simulado" if simulada else "resultado_con_aprendizaje")
    )
    if comparar_equipo:
        resultado_clave += "_equipo"
    if buscar:
        st.session_state.pop(resultado_clave, None)
        if tipos == []:
            st.warning("Has excluido todos los tipos de alojamiento. Quita alguna exclusión para buscar.")
            return
        if not simulada and not clave.strip():
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
        try:
            with st.spinner("Eligiendo destinos y comprobando vuelos y alojamientos…"):
                consultar = consultar_catalogo_ficticio if simulada else lambda parametros: consultar_serpapi(
                    clave.strip(), parametros,
                )
                consultas = {}

                def consultar_filtrado(parametros):
                    if not comparar:
                        return consultar_con_filtros(consultar, parametros, tipos, nota_minima)
                    clave_consulta = tuple(sorted(parametros.items()))
                    if clave_consulta not in consultas:
                        consultas[clave_consulta] = consultar_con_filtros(
                            consultar, parametros, tipos, nota_minima,
                        )
                    return consultas[clave_consulta]

                if comparar:
                    gustos = f"Conservar: {imprescindibles}. Flexibles: {preferencias}"
                    comparar_metodos = comparar_un_agente_y_equipo if comparar_equipo else comparar_estrategias
                    resultados = comparar_metodos(
                        ClienteOllama(), consultar_filtrado, origen, fechas, gustos, adultos, presupuesto,
                    )
                    resultado = resultados, presupuesto, uuid4().hex
                else:
                    planes, registro, primer_total = planificar_con_alternativas(
                        ClienteOllama(), consultar_filtrado, origen, fechas, preferencias, adultos, presupuesto,
                        margen=margen, origen_fijo=origen_fijo, imprescindibles=imprescindibles,
                        experiencia=experiencia_aprendida, equipo=True, objetivo_opciones=objetivo_opciones,
                    )
                    resultado = planes, registro, primer_total, presupuesto, origen, adultos, margen, uuid4().hex
        except (ErrorOfertas, ErrorOllama) as error:
            st.error(str(error))
            return
        st.session_state[resultado_clave] = resultado
    if resultado_clave not in st.session_state:
        return
    resultado = st.session_state[resultado_clave]
    if comparar:
        if len(resultado) == 2:
            resultado = (*resultado, uuid4().hex)
            st.session_state[resultado_clave] = resultado
        resultados, limite, identificador = resultado
        mostrar_comparacion(resultados, limite, simulada)
        if st.button("Guardar esta comparación"):
            DatosViaje().guardar_comparacion(identificador, resultados, limite, simulada)
            st.success("Comparación guardada. Puedes abrirla en Demostraciones.")
        return
    mostrar_resultado(resultado, demostracion=simulada, ficticia=simulada)
    if not simulada and st.button("Guardar esta búsqueda para la demo"):
        DatosViaje().guardar_demostracion(resultado)
        st.success("Búsqueda guardada. Puedes abrirla en el modo demostración.")


def mostrar_comparacion(resultados, presupuesto, simulada=True):
    st.subheader("Comparación con datos ficticios" if simulada else "Comparación con ofertas reales")
    if not simulada:
        st.caption("La tabla separa los precios confirmados de las tarifas con impuestos pendientes. Los precios corresponden a la consulta.")
    balance = balance_comparacion(resultados, presupuesto)
    st.subheader("¿Qué consiguió cada método?")
    st.info(balance["titulo"])
    st.table([{
        "Método": "IA con plan inicial" if m["metodo"] == "Lista fija" else m["metodo"],
        "Viaje dentro del presupuesto": "Sí" if m["viable"] else "No confirmado",
        "Mejor total comprobado": f"{m['total']:.2f} €" if m["total"] is not None else "Sin total",
        "Consultas de datos": m["consultas"] if m["consultas"] is not None else "No registradas",
        "Llamadas a Qwen3": m["llamadas_modelo"] if m["llamadas_modelo"] is not None else "No registradas",
        "Revisiones inválidas": m["revisiones_invalidas"] if m["revisiones_invalidas"] is not None else "No registradas",
    } for m in balance["metodos"]])
    st.caption("Se cuentan las decisiones del modelo. En el equipo se suman las de los cuatro roles.")
    es_equipo = resultados[1][0] == "Equipo de cuatro agentes"
    st.caption(
        "Un agente con herramientas y el equipo pueden revisar sus decisiones. El equipo reparte "
        "la búsqueda entre cuatro roles. Estas cifras describen esta ejecución."
        if es_equipo else
        "La lista fija mantiene sus propuestas; el planificador anterior puede revisarlas al conocer resultados."
    )
    evitadas = [m["hoteles_evitados"] for m in balance["metodos"]]
    if any(evitadas):
        st.write(f"Consultas de hotel evitadas porque el vuelo ya superaba el máximo: "
                 f"plan inicial {evitadas[0]} · agente {evitadas[1]}.")
        st.caption("Esta comprobación la hace Python en ambos métodos. Ahorra trabajo, pero no es una ventaja exclusiva del agente.")
    st.caption("Las consultas incluyen las reutilizadas desde caché: no equivalen a cargos de SerpApi. "
               "El agente añade llamadas al modelo para revisar. No medimos aquí horas de trabajo humano ni dinero ahorrado en la API.")
    filas = []
    for nombre, intentos, planes, _ in resultados:
        provisional = min((plan["total"] for plan in planes if not plan.get("impuestos_confirmados", True)),
                          default=None)
        total = min((plan["total"] for plan in planes if plan.get("impuestos_confirmados", True)), default=None)
        filas.append({
            "Método": nombre,
            "Destinos y fechas consultados": ", ".join(
                f"{CIUDADES[intento['aeropuerto']]} ({intento['ida']} a {intento['vuelta']})"
                for intento in intentos
            ),
            "Intentos": len(intentos),
            "Consultas al proveedor (incluye caché)": (
                sum(i.get("consultas_proveedor", 0) for i in intentos)
                if all("consultas_proveedor" in i for i in intentos) else "No registrado"
            ),
            "Mejor coste del grupo": f"{total:.2f} €" if total is not None else "Sin precio completo",
            "Mejor tarifa con impuestos pendientes": f"{provisional:.2f} €" if provisional is not None else "—",
            f"¿Dentro de {presupuesto} €?": (
                "Sí" if total is not None and total <= presupuesto
                else "Por confirmar" if provisional is not None and provisional <= presupuesto else "No"
            ),
        })
    with st.expander("Ver precios, rutas y consultas en detalle"):
        st.table(filas)
        st.caption(f"Comparación del menor precio, independientemente del presupuesto: {evaluar_comparacion(resultados)}.")
    st.caption("Mismo máximo de intentos por método. Un intento puede necesitar varias consultas de vuelo y hotel. Las consultas idénticas reutilizan datos; el agente añade llamadas a Qwen3 para revisar.")
    fija, adaptativa = resultados
    rutas = lambda fila: [(i["aeropuerto"], i["ida"], i["vuelta"]) for i in fila[1]]
    if rutas(fija) == rutas(adaptativa):
        st.info("Ambos métodos consultaron las mismas opciones. Esta ejecución no demuestra una ventaja del replanteamiento.")
    elif all(fila["Mejor coste del grupo"] == "Sin precio completo" for fila in filas):
        st.info("Los métodos probaron opciones distintas. Ninguno obtuvo un total con impuestos confirmados.")
    elif filas[0]["Mejor coste del grupo"] == filas[1]["Mejor coste del grupo"]:
        st.info("Los métodos consultaron opciones distintas y obtuvieron el mismo mejor coste.")
    st.subheader("Cómo cambió la búsqueda del agente")
    resumen = []
    for numero, intento in enumerate(adaptativa[1], 1):
        resumen.append({
            "Paso": numero,
            "Consulta": f"{CIUDADES[intento['aeropuerto']]} · {intento['ida']}",
            "Resultado observado": diagnosticar(intento, presupuesto),
            "Siguiente decisión": intento.get("siguiente_decision", "Fin de los intentos disponibles"),
        })
    st.table(resumen)
    if len(resultados[0][1]) < 2:
        st.info("Qwen3 solo propuso una búsqueda. En este caso no hubo un segundo intento que replantear.")
    for nombre, _, _, traza in resultados:
        with st.expander(f"Ver decisiones · {nombre}"):
            for paso in traza:
                st.write(paso)


def mostrar_demostraciones(origen_demo):
    if origen_demo == "Comparaciones guardadas":
        comparaciones = DatosViaje().comparaciones_guardadas()
        if not comparaciones:
            st.info("Aún no hay comparaciones guardadas.")
            return

        reales = [datos for _, datos in comparaciones if len(datos) > 2 and not datos[2]]
        if reales:
            st.subheader("Balance de las comparaciones reales guardadas")
            balance = Counter(balance_comparacion(datos[0], datos[1])["categoria"] for datos in reales)
            st.table([{"Resultado": etiqueta, "Comparaciones": cantidad} for etiqueta, cantidad in balance.items()])
            st.caption("Primero se comprueba si se consiguió un viaje dentro del presupuesto. "
                       "El balance solo resume los casos que decidiste guardar, no una muestra representativa de todos los viajes.")

        def etiqueta_comparacion(indice):
            fecha, resultado = comparaciones[indice]
            limite = resultado[1]
            return f"Comparación {len(comparaciones) - indice} · {limite} € de grupo · {fecha} UTC"

        indice = st.selectbox("Comparación guardada", range(len(comparaciones)), format_func=etiqueta_comparacion)
        mostrar_comparacion(*comparaciones[indice][1])
        return
    st.info("Estás viendo resultados guardados. Los precios y la disponibilidad corresponden a la consulta original.")
    demostraciones = DatosViaje().demostraciones()
    if not demostraciones:
        st.write("Aún no hay búsquedas guardadas. Haz una búsqueda real y pulsa «Guardar esta búsqueda para la demo».")
        return

    def etiqueta(indice):
        fecha, resultado = demostraciones[indice]
        return f"{CIUDADES[resultado[4]]} · {resultado[5]} adultos · {resultado[3]} € de grupo · {fecha} UTC"

    indice = st.selectbox("Búsqueda guardada", range(len(demostraciones)), format_func=etiqueta)
    mostrar_resultado(demostraciones[indice][1], demostracion=True)


def mostrar_resultado(resultado, demostracion=False, ficticia=False):
    planes, registro, primer_total, limite, salida, personas, margen, busqueda = resultado
    st.subheader(f"Opciones desde {CIUDADES[salida]}")
    maximo = limite + margen
    st.caption(f"{personas} adultos · presupuesto del grupo: {limite} € · máximo con margen: {maximo} €")
    descartados = [plan for plan in planes if plan["total"] > maximo]
    planes = [plan for plan in planes if plan["total"] <= maximo]
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
    elif not validos and descartados and not provisionales:
        st.info("No encontramos un viaje dentro de tu máximo. Las ofertas que lo superan se descartaron.")
    elif not validos and not provisionales:
        st.info("No encontramos un viaje con total confirmado dentro del máximo en las consultas realizadas. "
                "En el detalle puedes ver si faltan ofertas o si los vuelos comprobados ya superaban el límite.")
        if salida == "LEN":
            st.caption("¿Te serviría salir desde Valladolid o Madrid? Puedes elegir otro aeropuerto en el formulario. "
                       "El precio mostrado no incluye el traslado desde León.")
        else:
            st.caption("¿Puedes ampliar las fechas o salir desde otro aeropuerto? Puedes ajustar el formulario.")
    for plan in (validos or planes)[:3]:
        mostrar_plan(plan, salida, personas, limite, ficticia)
    if not validos and provisionales:
        st.markdown("**Alternativas con impuestos pendientes de confirmar**")
        for plan in provisionales[:3]:
            mostrar_plan(plan, salida, personas, limite, ficticia)
    mostrados = (validos or planes)[:3] + (provisionales[:3] if not validos else [])
    if not demostracion and any(plan.get("salida", salida) != salida for plan in mostrados):
        aprender_salida(salida, busqueda)
    if not ficticia:
        st.caption("Precios de la consulta. Comprueba la disponibilidad y el importe final antes de reservar. "
                   "El presupuesto comparado cubre solo vuelo y alojamiento.")
    with st.expander("Qué aportó revisar alternativas", expanded=True):
        st.caption("Este resumen compara con detenerse en la primera propuesta. Para medir frente a una lista con varios intentos, usa Comparar IA y agente.")
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
    trabajo_equipo = any(paso.startswith("[Coordinación]") for paso in registro)
    if trabajo_equipo:
        st.markdown("**Trabajo del equipo de agentes**")
        st.caption("Cada línea muestra la decisión de un especialista o el informe que recibió Coordinación.")
    with st.expander("Qué se consultó y cómo se eligieron las combinaciones",
                     expanded=trabajo_equipo or not validos):
        for paso in registro:
            st.write(paso)



def mostrar_plan(plan, salida, personas, limite, ficticia):
    ida, vuelta = plan["ida_fecha"], plan["vuelta_fecha"]
    salida_real = plan.get("salida", salida)
    impuestos = plan.get("impuestos_confirmados", True)
    st.subheader(f"{plan['ciudad']} · {plan['total']:.2f} €")
    if salida_real != salida:
        st.info(f"Salida alternativa: {CIUDADES[salida_real]}. El traslado desde {CIUDADES[salida]} queda fuera del precio.")
    if plan.get("preferencias_omitidas"):
        st.caption("Preferencias flexibilizadas: " + ", ".join(plan["preferencias_omitidas"]))
    st.write(f"{ida:%d/%m/%Y} a {vuelta:%d/%m/%Y} · {plan['nombre']}")
    st.caption(f"{plan['total'] / personas:.2f} € por persona.")
    if not impuestos:
        st.caption("Total provisional. Confirma los impuestos de la estancia y el importe final antes de decidir.")
    elif plan["total"] > limite:
        st.caption(f"{plan['total'] - limite:.2f} € por encima de tu límite.")
    st.write(f"Vuelos del grupo: {plan['vuelo']:.2f} € · Estancia: {plan['alojamiento']:.2f} €")
    nota = plan.get("nota_alojamiento")
    if isinstance(nota, (int, float)) and 0 < nota <= 5:
        st.caption(f"Valoración de huéspedes: {nota:g} de 5.")
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
    if ficticia:
        return
    vuelo, estancia = st.columns(2)
    fechas = f"{ida.isoformat()} a {vuelta.isoformat()}"
    consulta_vuelo = f"vuelos {salida_real} {plan['ciudad']} {fechas} {personas} adultos {' '.join(numeros)}"
    consulta_hotel = f"{plan['nombre']} {plan['ciudad']} {fechas} {personas} adultos"
    enlace = plan.get("enlace_vuelos")
    if enlace:
        vuelo.link_button("Abrir ruta y fechas en Google Flights", enlace)
    else:
        vuelo.link_button("Buscar los datos del vuelo", "https://www.google.com/search?" + urlencode({"q": consulta_vuelo}))
    estancia.link_button("Comprobar alojamiento", "https://www.google.com/travel/hotels?" + urlencode({"q": consulta_hotel}))
    st.caption("Los enlaces abren una búsqueda con los datos del plan. El precio puede cambiar.")


def aprender_salida(origen, busqueda):
    if st.button("Para este viaje prefiero mantener mi aeropuerto"):
        total = DatosViaje().registrar_rechazo_salida(origen, busqueda)
        st.session_state.rechazo_salida = (busqueda, total)
    rechazo = st.session_state.get("rechazo_salida")
    if not rechazo or rechazo[0] != busqueda:
        return
    total = rechazo[1]
    st.caption(f"Has descartado un cambio de aeropuerto desde {CIUDADES[origen]} en {total} búsquedas.")
    if total >= 2 and not st.session_state.get("fijar_salida"):
        def confirmar():
            perfil = {**st.session_state.perfil_ofertas, "origen": origen, "origen_fijo": True}
            DatosViaje().guardar_prioridades_ofertas(perfil)
            st.session_state.perfil_ofertas = perfil
            st.session_state.fijar_salida = True

        st.button(f"Recordar que prefiero salir desde {CIUDADES[origen]}", on_click=confirmar)
