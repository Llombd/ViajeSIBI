# Agente de recomendación de viajes

Proyecto universitario de IA agéntica: un asistente que interpretará preferencias en lenguaje natural, decidirá qué herramientas consultar y recomendará hasta tres destinos apoyándose en sus resultados.

**Estado:** etapas 1, 2 y 3 implementadas. Agente por terminal e interfaz local opcional con Ollama local y qwen3:4b. Pasan 118 pruebas con la interfaz instalada (109 del núcleo y 9 de interfaz), incluidas las 11 originales. No se utilizan claves ni APIs de pago.

## Conceptos básicos

Un **LLM** es un modelo de lenguaje ya entrenado. Una **herramienta** es una función que consulta datos o realiza un cálculo. El **agente** combina el LLM, herramientas, instrucciones e historial en un bucle de decisiones. No entrenamos un modelo desde cero.

Las herramientas usan filtros y fórmulas. La parte agéntica está en que el LLM elige qué consultar, observa los resultados y decide si necesita otra herramienta, una aclaración o una respuesta final.

## Alcance

- Conversación en español; inicialmente mediante terminal.
- Un único agente y tres herramientas.
- Catálogo local de exactamente 15 destinos europeos.
- Todos los costes, actividades y valores de clima son ficticios, identificados como datos de demostración. Los nombres de ciudades y países corresponden a lugares europeos.
- Presupuesto total para todos los viajeros, incluyendo transporte de ida y vuelta, alojamiento y gastos diarios.
- Preferencias previstas: origen, fechas o mes, duración, viajeros, presupuesto, región e intereses.
- Sin reservas ni pagos. Incorporaremos alguna fuente externa real después de validar el agente.

Las instrucciones piden al agente que pregunte si faltan datos necesarios y explique si no hay opciones viables, sin cambiar restricciones por su cuenta. El cumplimiento de estas instrucciones se evaluará con más detalle en las etapas 4 y 5.

## Arquitectura

El agente y la terminal usan Python y su biblioteca estándar. La interfaz opcional utiliza Streamlit. El catálogo está en JSON. El modelo qwen3:4b se ejecuta en Ollama local. Python envía peticiones HTTP a http://localhost:11434/api/chat mediante urllib.request. No se usa un SDK, una API de pago ni claves.

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

El bucle implementado funciona así:

1. Recibir el mensaje y añadirlo al historial.
2. Consultar al LLM con instrucciones, historial y herramientas disponibles.
3. Si solicita herramientas, ejecutarlas, añadir sus resultados y volver al paso 2.
4. Si pide una aclaración, mostrarla y esperar al usuario.
5. Si entrega la recomendación, terminar el turno.

Los límites son doce llamadas al modelo y diez intentos de ejecución de herramientas por turno; las llamadas inválidas también cuentan. Cada petición HTTP tiene un tiempo de espera de 120 segundos, sin reintentos automáticos. Al alcanzar un límite, el programa detiene el turno y lo explica. No hay una secuencia fija de herramientas. La terminal muestra nombres, argumentos y resultados.

El modelo elige una acción por consulta mediante un objeto JSON con herramienta, argumentos y respuesta. Para una respuesta final con precios, argumentos contiene una propuesta estructurada (tipo, destinos, origen, duracion_dias, viajeros y presupuesto_total); Python genera el texto mostrado. herramienta puede ser cualquiera de las tres funciones o ninguna para preguntar o responder. Se usa un esquema en el campo format de Ollama, según su [documentación de salidas estructuradas](https://docs.ollama.com/capabilities/structured-outputs). No usamos llamadas nativas: en la prueba con la plantilla instalada, el modelo generaba razonamiento largo en texto. El formato JSON permitió obtener decisiones ejecutables sin imponer una secuencia de herramientas.

Usamos think: false según la [documentación de thinking](https://docs.ollama.com/capabilities/thinking) y /no_think en las instrucciones, un interruptor descrito por [Qwen3](https://qwenlm.github.io/blog/qwen3/). stream: false permite recibir una respuesta completa. El contexto está configurado en 8192 tokens y la salida en un máximo de 1024 tokens por consulta. Son ajustes iniciales para el Mac de 8 GB, no una garantía de consumo o rendimiento. Si Ollama indica que la salida fue truncada, el cliente devuelve un error en vez de presentar una respuesta incompleta.

El historial vive en memoria durante la sesión; no se guarda en disco. El cliente conserva mensajes, llamadas y resultados y no muestra el campo thinking. Las conversaciones muy largas pueden superar la ventana de contexto del modelo: no hay resumen automático en esta etapa. Si una petición falla, se descarta el turno fallido y se conservan los anteriores.

Las recomendaciones y los precios no se aceptan en texto libre. Cada ID propuesto debe tener un resultado exitoso de estimar_coste para el mismo origen, duración y viajeros. Python redacta los importes exactos de ese resultado; no utiliza precios escritos por el modelo ni convierte el presupuesto del usuario en un precio.

Para tipo=recomendacion, además se comprueba que el coste total de cada destino no supere el presupuesto total expresado por el usuario. Para tipo=coste, se puede mostrar un coste consultado aunque supere el presupuesto, sin recomendarlo ni afirmar que cumple. Se ignora el texto libre que acompañe una propuesta estructurada: no puede sustituir los datos verificados.

Una validación fallida bloquea toda la propuesta, elimina el texto inválido del historial y devuelve el motivo al LLM. El modelo puede consultar otras opciones. Si agota los límites, solo se muestra el mensaje de límite, nunca la propuesta rechazada. No se fuerza una secuencia de herramientas.

Antes de ejecutar buscar_destinos, se elimina una región propuesta por el modelo si no aparece explícitamente en los mensajes del usuario. Se reconocen sur, oeste, centro y norte, además de expresiones como Europa occidental. Una preferencia explícita persiste entre turnos; frases como cualquier región, toda Europa o nos da igual la región eliminan esa restricción. El programa no deduce una región de la ciudad de salida. Esta comprobación es deliberadamente sencilla; ante expresiones ambiguas el agente debe preguntar.

Los intereses también se contrastan con los mensajes reales del usuario, nunca con ejemplos del prompt, preguntas del agente o correcciones internas. Se reconocen cultura/cultural/culturales, gastronomía y sus adjetivos, playa(s) y naturaleza. Los filtros no respaldados se eliminan antes de ejecutar y registrar la búsqueda. «Barato por Europa» no implica ninguno de esos intereses: permite buscar_destinos({}). Las exclusiones simples como «no queremos playa» no se convierten en intereses positivos. «Sin intereses concretos» elimina una preferencia anterior. Es una comprobación conservadora con vocabulario limitado; no pretende interpretar cualquier expresión de gustos.

Si una búsqueda devuelve una lista vacía, el resultado avisa al LLM de que revise sus filtros. La validación bloquea conclusiones generales sobre la ausencia de destinos si no se ha buscado o si la última consulta tenía filtros. Se puede explicar que no hay coincidencias con esos filtros y preguntar si el usuario desea flexibilizar preferencias explícitas. El programa no elimina gustos auténticos ni ejecuta una secuencia fija de herramientas para conseguir coincidencias.

Las preguntas deben priorizar origen, duración, viajeros y presupuesto. Región e intereses son opcionales. Una comprobación sencilla de las menciones en los mensajes del usuario impide exigir estos filtros antes de completar los datos esenciales. El LLM sigue interpretando los valores y conserva el historial de la sesión; los costes solo se muestran tras la validación ya descrita.

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

Estos cinco casos concretan el alcance acordado y se guardan también en evals/casos.json. Sirven para probar el agente; su evaluación sistemática sigue pendiente.

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
| 3. Bucle mínimo | Ollama, qwen3:4b, historial, validación, límites y terminal implementados. | Llamadas elegidas por el modelo, resultados devueltos y respuesta final; pruebas del bucle sin servidor. |
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
  main.py              Conversación interactiva y manejo de errores
  agent.py             Cliente HTTP de Ollama, schemas, validación y bucle
  prompts.py           Instrucciones en español para el modelo
  presentacion.py      Resumen, tabla y explicaciones de datos validados
data/
  destinos.json        Los 15 destinos y todos los datos ficticios
tests/
  test_tools.py        Las 11 pruebas originales de herramientas
  test_agent.py        84 pruebas del bucle, cliente y regresiones con respuestas simuladas
  test_presentacion.py 14 pruebas del formato, márgenes y datos mostrados
evals/
  casos.json           Cinco escenarios; sin evaluador automático del LLM
.env.example           Indica que Ollama local no necesita credenciales
.gitignore             Excluye cachés, entorno virtual y secretos
pyproject.toml         Metadatos y Python mínimo; sin dependencias externas
~~~

## Ejecutar las pruebas

Necesitas Python 3.10 o posterior. No hace falta instalar paquetes, conectar internet ni configurar una clave API. Desde una terminal:

~~~bash
cd /Users/lucia/Documents/viajeSIBI
python3 -m unittest discover -s tests -v
~~~

Hay 109 pruebas del núcleo. Se conservan las 11 originales de herramientas y las pruebas del bucle adaptadas al formato de salida verificado. Las regresiones reproducen el caso de Bruselas, presupuestos copiados como precios, precios de otros destinos, parámetros distintos, resultados fallidos, propuestas por encima del presupuesto, bloqueo al agotar límites y filtros regionales inventados. También comprueban que el modelo puede seguir consultando y recomendar una alternativa verificada. Las nueve regresiones adicionales cubren el viaje barato de dos turnos, intereses inventados o excluidos, persistencia de preferencias, indiferencia regional, búsquedas vacías y prioridad de datos esenciales. Las 14 regresiones de recomendaciones múltiples comprueban cierre prematuro, cantidades solicitadas, costes reutilizados, menos opciones válidas, límites, duplicados y filtros. Las 14 pruebas de presentación comprueban resumen, orden, columnas, márgenes, opciones únicas, intereses, presupuestos ausentes o inventados, fuentes verificadas y continuidad del contexto. Las 13 regresiones de cierre cubren presupuestos insuficientes, descartes, límites, respuestas parciales y cambios de parámetros. Todas pasan sin Ollama; no son una evaluación exhaustiva de la calidad lingüística del modelo.

Ejemplo de uso en Python, desde la carpeta del proyecto:

~~~python
from src.tools import buscar_destinos, consultar_destino, estimar_coste

print(buscar_destinos(region="sur", intereses=["cultura", "gastronomía"]))
print(consultar_destino("lisboa", mes=5))
print(estimar_coste("lisboa", origen="Madrid", duracion_dias=4, viajeros=2))
~~~

## Ejecutar el agente con Ollama

Con Python 3.10 o posterior y el modelo ya descargado, abre la aplicación Ollama en tu Mac. Si prefieres iniciar el servidor desde la terminal:

~~~bash
ollama serve
~~~

Déjalo ejecutándose y abre otra terminal. Si indica que el puerto ya está ocupado, normalmente Ollama ya está abierto; no necesitas un segundo servidor.

Comprueba el modelo y ejecuta el agente:

~~~bash
ollama list
cd /Users/lucia/Documents/viajeSIBI
python3 -m src.main
~~~

La lista debe incluir qwen3:4b. Ya está descargado en este proyecto; si alguna vez falta, se puede descargar con ollama pull qwen3:4b. No hace falta ejecutar ollama run por separado.

Escribe, por ejemplo:

> Quiero cuatro días de cultura en mayo desde Madrid para dos personas, con 900 euros en total incluyendo transporte, alojamiento y gastos diarios. Recomiéndame un destino.

La terminal mostrará líneas como [Herramienta] buscar_destinos(...) y [Resultado] con los datos. Las llamadas exactas las decide el modelo. Después pregunta:

> ¿Y cuánto costaría Lisboa manteniendo esos mismos datos?

Esto permite observar si reutiliza las preferencias del historial. Escribe salir para terminar; también puedes usar Ctrl+C. El historial se pierde al cerrar el programa.

La regresión automatizada reproduce la petición de cuatro días desde Madrid, dos personas y 800 EUR en total: rechaza Bruselas sin estimación, vuelve a rechazarla si supera el presupuesto y permite continuar hasta recomendar Oporto con su coste calculado de 770 EUR. La búsqueda se realiza sin región si el usuario no la indicó.

La misma petición se ha probado con Ollama y qwen3:4b: buscó destinos culturales sin región, intentó propuestas que fueron bloqueadas, consultó Lisboa (910 EUR, fuera del presupuesto) y después Oporto (770 EUR). La respuesta final mostró únicamente Oporto, con 770 EUR para el grupo y 385 EUR por persona. Las llamadas exactas pueden variar entre ejecuciones; el límite sigue impidiendo bucles infinitos.

El fallo anterior ocurría porque el validador reunía importes de toda la conversación, incluido el presupuesto del usuario, sin asociarlos a destinos o parámetros. Además, el filtro regional dependía únicamente del prompt y seis consultas dejaban poco margen para las correcciones. La solución mantiene la elección de herramientas en el LLM y traslada la comprobación y presentación de precios al programa.

Estos cambios corrigen la validación y presentación de precios. La interpretación de preferencias por el modelo y la comprensión de expresiones ambiguas siguen requiriendo evaluación en la etapa 4.
Si no conecta, comprueba que Ollama está abierto. Si hay un error HTTP, revisa ollama list y tu versión de Ollama: debe admitir herramientas y el parámetro think. No se utiliza una conexión externa para inferencia ni para las herramientas del catálogo.

El siguiente paso es mejorar y evaluar la calidad de la conversación en la etapa 4. La conexión local y el bucle están implementados; la fuente de viajes sigue siendo ficticia.

La regresión de «Quiero hacer un viaje barato por Europa» usa respuestas simuladas: primero rechaza exigir región mientras faltan datos esenciales; después, con Madrid, 4 días, 2 personas, 800 EUR y región indiferente, corrige una llamada que inventaba los cuatro intereses y ejecuta la búsqueda sin filtros. Recupera los 15 destinos y permite mostrar Oporto por 770 EUR únicamente después de estimar_coste. Esta corrección se ha verificado con pruebas automáticas, sin una nueva ejecución del modelo real.

## Formato de recomendaciones en terminal

La respuesta final se presenta en este orden:

1. Datos del viaje: origen, días, viajeros, presupuesto total e intereses reconocidos en la conversación. Los intereses son opcionales; se muestra «No indicados» si faltan.
2. Tabla de una a tres opciones consultadas por el LLM y validadas por Python, ordenadas por coste total ascendente.
3. Explicaciones breves que relacionan las etiquetas del catálogo con los intereses del usuario. Si no hay coincidencia, se indica; no se inventa afinidad.

La tabla incluye destino, país, coste total del grupo, coste por persona, margen disponible y características del catálogo. El margen se calcula como presupuesto total menos coste total, nunca lo genera el LLM. El resumen del viaje usa los parámetros de las estimaciones verificadas y el presupuesto de la conversación. No se añaden destinos sin estimación para completar filas ni se evalúan automáticamente los precios de todo el catálogo: el LLM sigue eligiendo las consultas. En peticiones múltiples, Python reúne hasta la cantidad solicitada entre los destinos que el modelo ya ha evaluado para ese viaje, respetando preferencias y presupuesto.

Las explicaciones se construyen en Python con etiquetas del catálogo; no añaden actividades, clima, precios ni ventajas redactados libremente por el modelo. Si no hay intereses, se muestran características sin atribuir preferencias al usuario. La presentación está separada en src/presentacion.py; las comprobaciones de origen, duración, viajeros, presupuesto y estimaciones continúan en src/agent.py.

Ejemplo con datos ficticios: Madrid, 4 días, 2 viajeros, 1400 EUR en total e interés en cultura. Si el modelo consulta y propone estas tres opciones, la tabla será:

~~~text
| Destino | País     | Coste total | Por persona | Margen disponible | Características      |
|---------|----------|-------------|-------------|-------------------|----------------------|
| Oporto  | Portugal | 770 EUR     | 385 EUR     | 630 EUR           | cultura, gastronomía |
| Lisboa  | Portugal | 910 EUR     | 455 EUR     | 490 EUR           | cultura, gastronomía |
| Roma    | Italia   | 1180 EUR    | 590 EUR     | 220 EUR           | cultura, gastronomía |
~~~

Después se explica, por ejemplo: «Oporto: Coincide con tus intereses en cultura. Su coste comprobado está dentro del presupuesto». El orden solo compara las opciones mostradas, sin afirmar que sean las más baratas del catálogo. Si se solicita una sola, solo se necesita una opción válida. Si se solicitan varias, el agente intenta completar la comparación antes de terminar.

Las consultas de tipo coste también utilizan la tabla, pero no se presentan como recomendaciones: sin presupuesto conocido, el margen es «No disponible»; si el coste supera un presupuesto conocido, el margen es negativo y no se afirma compatibilidad.

Para probar la presentación sin Ollama:

~~~bash
python3 -B -m unittest discover -s tests -p 'test_presentacion.py' -v
~~~

Para probarla conversando, abre Ollama y ejecuta desde la carpeta del proyecto:

~~~bash
python3 -m src.main
~~~

Petición sugerida: «Somos dos personas, queremos viajar cuatro días desde Madrid, con 1400 EUR en total para transporte, alojamiento y gastos diarios. Nos gusta la cultura. Propón hasta tres destinos que hayas comprobado». El número y los destinos dependen de las decisiones del modelo y de los límites del bucle; no se garantiza que consulte tres.

## Cuando se solicitan varias recomendaciones

El agente reconoce peticiones como «hasta tres destinos», «dos alternativas» o «varias recomendaciones», con un máximo de tres. Los números de viajeros o días no se interpretan como cantidad de destinos. Una petición posterior de un solo destino o una consulta de precio conserva ese alcance.

Si el modelo intenta cerrar con una opción y el usuario ha solicitado varias, se revisan los costes verificados para el mismo origen, duración y viajeros. Se reúnen opciones distintas que cumplan el presupuesto y las preferencias explícitas, ordenadas por coste. Si todavía faltan opciones, quedan candidatos compatibles sin estimar y hay consultas disponibles, el programa devuelve al LLM el motivo y los IDs pendientes para que elija qué consultar. No ejecuta por su cuenta una secuencia de herramientas ni obtiene precios directamente del catálogo.

El modelo puede buscar, consultar detalles o estimar otros destinos. No necesita volver a estimar costes ya disponibles para el mismo viaje. Los resultados fallidos, los costes de otro viaje, las opciones fuera de presupuesto o incompatibles con los filtros no sirven para completar la tabla. Repetir una estimación no crea una opción distinta.

Se conservan los límites de doce consultas al modelo y diez intentos de herramienta por turno. Si se agotan, se muestra la tabla de opciones válidas disponibles, aunque sean una o dos, y se aclara que quedan candidatos sin comprobar. No se afirma que sean las únicas opciones válidas del catálogo. Si se ha comprobado el coste de todos los candidatos compatibles y realmente hay menos opciones válidas que las solicitadas, se indica ese resultado. En ningún caso se inventan filas o precios.

Esta ampliación se ha verificado con 14 pruebas automáticas adicionales y respuestas simuladas de Ollama; no requiere el servidor ni supone una nueva evaluación exhaustiva del modelo real. Para probarla en la terminal, inicia Ollama y ejecuta:

~~~bash
python3 -m src.main
~~~

Ejemplo: «Somos dos personas, queremos cuatro días desde Madrid, tenemos 1400 EUR en total para transporte, alojamiento y gastos diarios. Nos gusta la cultura. Recomiéndame hasta tres destinos distintos». El resumen, la tabla y las explicaciones mantienen el formato anterior; los avisos de continuación permiten observar los intentos de completar las opciones dentro de los límites.

## Respuesta útil al alcanzar los límites

El cierre no depende de que Qwen3 redacte correctamente la respuesta final. Después de cada estimación exitosa se conserva el contexto comprobado del viaje, incluso si su coste supera el presupuesto y aunque se haya solicitado una sola recomendación.

Cuando se agotan las consultas al modelo o los intentos de herramienta:

- Si hay destinos válidos, Python conserva el resumen, la tabla ordenada y las explicaciones. Muestra solo las opciones verificadas y distingue una búsqueda incompleta de una revisión de todos los candidatos compatibles.
- Si ninguno de los destinos comprobados cumple, se muestra una tabla separada de «Destinos comprobados fuera de presupuesto (no recomendados)», con costes, márgenes negativos y cuánto excede cada uno el presupuesto. No se presentan como recomendaciones.
- Se indica cuántos candidatos compatibles siguen sin coste verificado. Solo si todos tienen una estimación exitosa para el mismo origen, duración y viajeros se permite concluir que ninguno de esos candidatos cumple el presupuesto. Los errores y costes de otros viajes no justifican esa conclusión.
- Si no hay resultados exitosos relevantes o falta presupuesto comprobable, no se inventa una tabla ni una conclusión sobre precios.

Un destino descartado se señala al modelo para que elija otra consulta. Si vuelve a solicitar el mismo coste y sigue fuera del presupuesto actual, se reutiliza el resultado verificado, sin recalcularlo. El intento sigue contando para el límite. Un cambio de presupuesto o de parámetros permite reconsiderar el destino. No se modifican automáticamente las preferencias ni el presupuesto.

Ejemplo de cierre comprobado con herramientas reales y decisiones simuladas: dos viajeros, cuatro días desde Madrid, cultura y 500 EUR en total. Tras consultar Lisboa (910 EUR), Oporto (770 EUR) y Barcelona (990 EUR), la salida muestra esos costes como descartados y explica que quedan 12 candidatos compatibles sin verificar. No afirma que no existan destinos válidos en todo el catálogo.

Esta mejora incluye 13 pruebas automáticas adicionales. Se ejecutan junto con las anteriores sin conectar Ollama:

~~~bash
python3 -B -m unittest discover -s tests
~~~

## Cambios de presupuesto sin moneda

Si escribes «tenemos 1400» o «presupuesto máximo: 1400», el programa pregunta si se trata del presupuesto total en EUR antes de consultar al modelo. No conserva un presupuesto anterior como si siguiera confirmado ni repite validaciones hasta agotar el turno. Responde, por ejemplo, «1400 EUR en total»; un «sí» sin importe y moneda mantiene la aclaración pendiente. Los demás datos del viaje y los costes comprobados permanecen en el historial. Cantidades de días, viajeros o destinos no se consideran presupuestos.

Ocho pruebas adicionales verifican la aclaración, la sustitución del presupuesto anterior, la confirmación, la conservación del viaje, los formatos numéricos, la exclusión de mensajes internos y las tres recomendaciones después de confirmar. Se ejecutan con el mismo comando de pruebas, sin Ollama.

## Interfaz local con Streamlit

La interfaz ofrece un chat, las mismas tablas verificadas, un desplegable de herramientas y validaciones por respuesta y un botón «Nueva conversación». Reutiliza el agente sin cambiar sus decisiones, costes ni límites. El historial se conserva por sesión de navegador; no se guarda en disco y puede perderse al recargar la página. No se comparte el agente entre sesiones. Los detalles de herramientas se pueden abrir cuando termina cada respuesta.

Desde la carpeta del proyecto, prepara un entorno separado (solo la primera vez):

~~~bash
cd /Users/lucia/Documents/viajeSIBI
python3 -m venv .venv
.venv/bin/python -m pip install 'streamlit>=1.32,<2'
~~~

Abre Ollama con el modelo `qwen3:4b` disponible. Para iniciar la interfaz:

~~~bash
cd /Users/lucia/Documents/viajeSIBI
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
~~~

Abre http://127.0.0.1:8501 en el navegador. Para detener la interfaz, pulsa Ctrl+C en la terminal que la inició. No necesitas claves ni cuentas. La aplicación escucha solo en tu Mac; las peticiones al modelo siguen dirigidas a Ollama local. El coste de los destinos es ficticio.

Prueba: «Somos dos personas, cuatro días desde Madrid, nos gusta la cultura y tenemos 1400 EUR en total. Recomienda hasta tres destinos». También puedes escribir «tenemos 1400» y confirmar la moneda en el siguiente mensaje. Si Ollama no responde, verás el error y podrás volver a enviar tu petición después de abrirlo. El botón «Nueva conversación» elimina el historial de esa sesión y empieza con otro agente.

La terminal anterior sigue disponible con `python3 -m src.main`. Streamlit es opcional para ese modo. `app.py` contiene únicamente la interfaz; el agente continúa en `src/agent.py`.

Para ejecutar todas las pruebas, incluidas las nueve pruebas de interfaz, sin necesitar Ollama:

~~~bash
.venv/bin/python -B -m unittest discover -s tests
~~~

Las pruebas de interfaz utilizan el simulador oficial de Streamlit y decisiones simuladas del modelo: comprueban inicio, memoria, tabla y trazas, errores recuperables y nueva conversación. Sin Streamlit se omiten esas nueve pruebas y siguen ejecutándose las 109 del agente, herramientas y presentación.

### Preguntas repetidas

El historial del agente conserva todos los mensajes, también en la interfaz. Si el modelo copia una pregunta anterior mientras faltan datos esenciales, Python sustituye esa repetición por una pregunta que enumera solo los datos pendientes. Por ejemplo, después de «4 personas en febrero de 2027», no vuelve a pedir viajeros: pregunta por origen, duración y presupuesto. El mes y el año permanecen en el historial; las estimaciones siguen sin ajustes por fechas. Las instrucciones también evitan asumir que el viaje es de estudios o que Madrid es el origen confirmado. Tres pruebas del agente y una de interfaz cubren esta regresión.

Las preguntas de aclaración pueden mencionar «euros» sin incluir importes, destinos ni afirmaciones de precios. Si se bloquean dos respuestas consecutivas, faltan datos imprescindibles y todavía no hay una estimación exitosa en el turno, el programa pregunta directamente por lo pendiente en lugar de agotar las consultas. No acepta presupuestos inventados y no aplica este cierre a una comparación con costes ya comprobados. Cuatro pruebas del agente y una de interfaz reproducen este caso.

Si modificas el código del agente mientras la interfaz está abierta, detén Streamlit con Ctrl+C y arráncalo de nuevo con el comando anterior para cargar el código actualizado. «Nueva conversación» reinicia el historial, pero no reinicia el servidor de Python.

### Semanas y orígenes sin costes

«Una semana» cuenta como duración indicada (7 días); el modelo utiliza días al llamar a las herramientas. Los orígenes disponibles se comprueban en las rutas del catálogo. Si escribes «desde León», el programa explica que solo dispone de transporte desde Madrid y pide un cambio explícito antes de continuar. No cambia León a Madrid por su cuenta ni inventa el coste del trayecto. Puedes confirmar «desde Madrid» para continuar la demostración conservando el resto de la conversación. La detección sencilla de origen reconoce «desde», «salimos de» y «salgo de» seguidos de una ciudad de una palabra; no es un reconocimiento general de direcciones. Cinco pruebas del agente y una de interfaz cubren semanas, origen no disponible, persistencia y cambio explícito.

Cuando el programa propone Madrid porque el origen no tiene costes, puedes responder «sí», «sí, por favor», «vale», «de acuerdo» o «desde Madrid». Una afirmación breve confirma únicamente esa propuesta pendiente; un «sí» sin pregunta previa no establece un origen. La confirmación se comunica al LLM y se conserva sin sustituir el texto original del usuario. Un error de Ollama permite reintentar la confirmación. Cuatro pruebas del agente y una de interfaz comprueban este comportamiento. Los errores tipográficos en ciudades no se corrigen silenciosamente: la alternativa sigue necesitando confirmación.

Tras confirmar Madrid con una respuesta breve, si aún faltan datos esenciales, Python pregunta directamente por ellos antes de llamar al modelo. Así la confirmación no provoca intentos de herramientas sin duración o presupuesto confirmado.
