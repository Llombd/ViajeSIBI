# Agente de recomendación de viajes

Proyecto universitario de IA agéntica: un asistente que interpretará preferencias en lenguaje natural, decidirá qué herramientas consultar y recomendará hasta tres destinos apoyándose en sus resultados.

**Estado:** etapas 1 y 2 implementadas (definición, catálogo y herramientas). Las 11 pruebas pasan. No hay un LLM conectado ni una conversación ejecutable.

## Conceptos básicos

Un **LLM** es un modelo de lenguaje ya entrenado. Una **herramienta** es una función que consulta datos o realiza un cálculo. El futuro **agente** combinará el LLM, herramientas, instrucciones e historial en un bucle de decisiones. No entrenaremos un modelo desde cero.

Las herramientas pueden usar filtros y fórmulas. La parte agéntica estará en que el LLM elija qué consultar, observe los resultados y decida si necesita otra herramienta, una aclaración o una respuesta final.

## Alcance

- Conversación en español; inicialmente mediante terminal.
- Un único agente y tres herramientas.
- Catálogo local de exactamente 15 destinos europeos.
- Todos los costes, actividades y valores de clima son ficticios, identificados como datos de demostración. Los nombres de ciudades y países corresponden a lugares europeos.
- Presupuesto total para todos los viajeros, incluyendo transporte de ida y vuelta, alojamiento y gastos diarios.
- Preferencias previstas: origen, fechas o mes, duración, viajeros, presupuesto, región e intereses.
- Sin reservas ni pagos. Incorporaremos alguna fuente externa real después de validar el agente.

Si faltan datos necesarios, el futuro agente preguntará. Si no hay opciones viables, lo explicará y propondrá qué restricción flexibilizar, sin cambiarla por su cuenta.

## Arquitectura

Python y biblioteca estándar bastan para las etapas actuales. El catálogo está en JSON. En la etapa 3 añadiremos un proveedor de LLM con llamadas a herramientas; la propuesta inicial contempla el SDK de OpenAI y Responses API, con modelo configurable.

~~~text
Usuario ↔ interfaz ↔ controlador del bucle ↔ LLM
                         ↕                  │
                      historial             │ solicita una herramienta
                         ↕                  ↓
                       registro ← validación y ejecución Python
                                            ↕
                                      catálogo local
                                            │
                     LLM ← controlador ← resultado
~~~

El controlador ejecutará únicamente herramientas registradas, validará argumentos y devolverá resultados al modelo. El historial permitirá reutilizar información.

El bucle futuro será:

1. Recibir el mensaje y añadirlo al historial.
2. Consultar al LLM con instrucciones, historial y herramientas disponibles.
3. Si solicita herramientas, ejecutarlas, añadir sus resultados y volver al paso 2.
4. Si pide una aclaración, mostrarla y esperar al usuario.
5. Si entrega la recomendación, terminar el turno.

Como límites iniciales proponemos seis llamadas al modelo y diez ejecuciones de herramientas por turno. No habrá una secuencia fija que obligue a usar las tres herramientas siempre. Registraremos acciones observables y errores, sin solicitar razonamiento interno.

La [documentación oficial de llamadas a herramientas](https://developers.openai.com/api/docs/guides/function-calling) explica el intercambio entre modelo, aplicación y resultados.

## Herramientas implementadas

| Función | Entrada | Resultado |
| --- | --- | --- |
| buscar_destinos | Región opcional y lista opcional de intereses | Destinos que cumplen la región y todos los intereses solicitados. Sin filtros devuelve los 15. |
| consultar_destino | Identificador y mes entero de 1 a 12 | Detalles, actividades y clima típico ficticio del mes. |
| estimar_coste | Identificador, origen, duración en días y viajeros | Desglose en EUR, total del grupo, total por persona y supuestos. |

Convenciones:

- Regiones internas: sur, oeste, centro y norte.
- Intereses: cultura, gastronomia, playa y naturaleza. La búsqueda admite tildes y mayúsculas.
- Todos los destinos tienen doce entradas mensuales. El clima típico ficticio no es una previsión.
- La duración y los viajeros deben ser enteros positivos.
- Solo Madrid tiene datos de transporte. Otro origen devuelve un error explícito.
- Alojamiento por persona y noche, no por habitación; se cuentan días menos uno como noches.
- No se ajustan costes por fechas, disponibilidad ni temporada.
- Los resultados son diccionarios convertibles a JSON. Una entrada inválida o dato ausente devuelve un diccionario con la clave error; una búsqueda sin coincidencias devuelve una lista vacía.

La fórmula del coste total del grupo es:

~~~text
viajeros × (
    transporte de ida y vuelta por persona
    + alojamiento por persona/noche × (días − 1)
    + gastos por persona/día × días
)
~~~

## Cinco casos de uso

Estos cinco casos concretan el alcance acordado; no estaban redactados previamente. Se guardan también en evals/casos.json. El comportamiento conversacional es una expectativa para la etapa 3, no una función implementada.

| Caso | Petición | Resultado esperado |
| --- | --- | --- |
| Cultura y presupuesto | Cuatro días en mayo desde Madrid, dos viajeros, 900 EUR en total y cultura. | Comparar costes: Lisboa cuesta 910 EUR y queda fuera; Oporto cuesta 770 EUR y cumple. |
| Playa | Cinco días en julio desde Madrid, dos viajeros, 1800 EUR en total, playa y región sur. | La búsqueda devuelve Barcelona y Atenas; consultar el mes 7 y estimar sus costes. |
| Información incompleta | «Quiero un viaje de naturaleza barato». | Se pueden buscar candidatos; el futuro agente aclarará origen, duración, viajeros, presupuesto y fechas cuando sean necesarios. |
| Sin opciones viables | Cuatro días de cultura desde Madrid para dos viajeros por 100 EUR en total. | Ninguna estimación cumple el presupuesto; el futuro agente explicará el problema sin inventar alternativas. |
| Cambio de preferencias | Tras consultar Lisboa en mayo, el usuario cambia a agosto y pide playa. | Buscar candidatos con playa y consultar el mes 8; el futuro agente conservará las demás preferencias confirmadas. |

## Desarrollo por etapas

| Etapa | Trabajo | Criterio de finalización |
| --- | --- | --- |
| 1. Definición | Objetivo, alcance y cinco casos de uso. Documentados. | Casos con resultados esperados. Los requisitos de la asignatura aún deben contrastarse con su enunciado. |
| 2. Datos y herramientas | Catálogo y tres funciones locales implementados; 11 pruebas verificadas. | Consultas, cálculos y errores comprobados con pruebas. |
| 3. Bucle mínimo | Conectar LLM, historial, validación y límites. Pendiente. | Llamadas elegidas por el modelo, resultados devueltos y respuesta final. |
| 4. Calidad de conversación | Aclaraciones, cambios de preferencias y respuesta fundamentada. Pendiente. | Manejar datos incompletos y restricciones incompatibles. |
| 5. Evaluación | Casos, registros, calidad, latencia y consumo. Pendiente. | Informe con resultados, errores y mejoras. |
| 6. Presentación | Memoria, demostración e interfaz sencilla si queda tiempo. Pendiente. | Ejecución documentada y explicación del bucle. |

Más adelante evaluaremos entre 10 y 15 escenarios, incluyendo fallo de herramienta. Mediremos cumplimiento de restricciones, respaldo de afirmaciones, utilidad de llamadas y terminación. No exigiremos una secuencia idéntica de herramientas en cada ejecución.

## Archivos

~~~text
README.md              Objetivo, arquitectura, casos y ejecución
src/
  __init__.py          Identifica el paquete Python
  tools.py             Tres herramientas locales
  main.py              Solo descripción; interfaz pendiente
  agent.py             Solo descripción; bucle pendiente
  prompts.py           Solo descripción; instrucciones pendientes
data/
  destinos.json        Los 15 destinos y todos los datos ficticios
tests/
  test_tools.py        Pruebas con unittest
evals/
  casos.json           Cinco escenarios; sin evaluador automático del LLM
.env.example           Indica que aún no se necesitan credenciales
.gitignore             Excluye cachés, entorno virtual y secretos
pyproject.toml         Metadatos y Python mínimo; sin dependencias externas
~~~

## Ejecutar las pruebas

Necesitas Python 3.10 o posterior. No hace falta instalar paquetes, conectar internet ni configurar una clave API. Desde una terminal:

~~~bash
cd /Users/lucia/Documents/viajeSIBI
python3 -m unittest discover -s tests -v
~~~

Hay 11 pruebas para el catálogo, filtros, clima mensual, cálculo de costes, viaje de un día, argumentos inválidos y rutas ausentes. Se han ejecutado correctamente: 11 pruebas, resultado OK.

Ejemplo de uso en Python, desde la carpeta del proyecto:

~~~python
from src.tools import buscar_destinos, consultar_destino, estimar_coste

print(buscar_destinos(region="sur", intereses=["cultura", "gastronomía"]))
print(consultar_destino("lisboa", mes=5))
print(estimar_coste("lisboa", origen="Madrid", duracion_dias=4, viajeros=2))
~~~

El siguiente paso será, en la etapa 3, conectar el LLM e implementar su bucle. No hay llamadas externas implementadas.
