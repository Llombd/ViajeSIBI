# Cómo presentar ViajeSIBI sin enseñar código

## La idea en una frase

«El usuario delega la búsqueda de un viaje con unas condiciones. El sistema propone,
consulta precios y puede revisar su plan al descubrir que una opción no sirve».

Un agente usa IA: no es lo contrario de una IA. Una IA que ya consulta herramientas,
observa resultados y vuelve a decidir también puede ser un agente. Por eso aquí
comparamos el mismo Qwen3 con un plan fijo y con la posibilidad de revisarlo.

## Qué enseñar en dos minutos

1. Abre **Demostraciones → Comparación simulada**. Indica que las ofertas son ficticias
   y que Qwen3 sí toma las decisiones durante la ejecución. Si usas **Comparar IA y agente**,
   las ofertas vienen de SerpApi y consumen cuota.
2. Explica el encargo: mismo origen, fechas permitidas, personas, gustos y presupuesto
   para ambos métodos. No elegimos nosotros el destino. La comparación mantiene fijo el
   origen y no añade margen. En la planificación normal se aplican las flexibilidades autorizadas.
3. Al acabar, empieza por **¿Qué consiguió cada método?**: viaje confirmado dentro del
   presupuesto, coste del grupo y consultas necesarias. Enseña el fracaso si lo hay.
4. Abre **Cómo cambió la búsqueda del agente**. Señala un resultado, la siguiente decisión
   y lo que ocurrió después. Si confirmó la lista inicial, dilo: no ha descubierto una alternativa.
5. Guarda la comparación para volver a mostrarla sin consumir la API. Una ejecución aislada
   explica el funcionamiento; no demuestra que el agente sea mejor en general.

## Qué valor se está midiendo

| Pregunta económica | Evidencia visible |
| --- | --- |
| ¿Resolvió el encargo? | Consiguió o no un viaje con total confirmado dentro del presupuesto. |
| ¿Consiguió mejor precio? | Diferencia entre dos opciones que SÍ cumplen el presupuesto. |
| ¿Cuánto trabajo requirió? | Consultas de datos; el agente añade llamadas al modelo. No equivale a tiempo humano ahorrado. |
| ¿Se adaptó a un problema? | Observación anterior y consulta posterior. Cambiar de destino no es un éxito por sí solo. |
| ¿Respetó lo autorizado? | Máximo con margen, fechas y filtros; preferencias libres orientan al modelo, no están verificadas por la API. |

Ejemplo ilustrativo del mecanismo, no resultado del piloto: el vuelo cuesta 950 € y el
máximo es 800 €. Python evita consultar el hotel de esa combinación. El agente recibe
ese dato y puede elegir otra ruta. Solo si la nueva consulta devuelve un total admisible
habremos conseguido un viaje. Esta recuperación está probada con herramientas y decisiones
simuladas; no debe presentarse como un caso real obtenido por Qwen3.

## Qué hace cada parte

- **Qwen3:** propone destinos/fechas y decide la siguiente consulta al recibir resultados.
- **Herramientas:** buscan vuelos y estancias; no son otros modelos autónomos.
- **Python:** calcula, valida, conserva resultados y bloquea combinaciones que no encajan.
- **SQLite:** recuerda prioridades confirmadas y comparaciones. No entrena Qwen3.

El descarte previo al hotel se aplica también a la lista fija: es una mejora del programa,
no una capacidad exclusiva de los agentes. No añadimos agentes solo para tener más nombres.

## Conclusión defendible a día de hoy

El ciclo de revisión funciona y puede probarse. El piloto de seis casos con Qwen3 del
9 de noviembre terminó en seis empates: todavía no demuestra mejor recomendación.
No hay que ocultarlo ni preparar una comparación que haga perder artificialmente al otro método.

Para demostrar una mejora de recomendación falta medir varios viajes con disponibilidad
variable y datos reales archivados, fijando los casos antes de probarlos. Los gustos libres
necesitan además evidencia sobre lugares o servicios. Una API de vuelos/hoteles no prueba
que un destino tenga la cerveza, playa o ambiente que busca el usuario.

## Enseñar cómo aprende de repeticiones

Abre **Aprendizaje**. Explica: «Después de varios viajes comparables, el sistema
propone cambiar el orden de búsqueda. Antes de guardar ese cambio, lo prueba».

1. Muestra los resultados de práctica y sus fechas: son experiencia de herramientas,
   no opiniones inventadas por el modelo. Las ofertas de este laboratorio son ficticias.
2. Ejecuta o abre un experimento guardado. Enseña qué propuso Qwen3. Puede decidir
   mantener la estrategia, y entonces no se afirma ninguna mejora.
3. Si hay candidata, compara viajes válidos, precio y número de consultas en otras fechas.
   Menos consultas con el mismo resultado es una posible mejora de eficiencia.
4. Enseña la decisión de adoptar o rechazar. Python aplica el criterio publicado.
5. Si se adoptó, ejecuta el siguiente viaje: usa la experiencia guardada, pero vuelve a
   comprobar precios. No reentrena el modelo y no aplica datos ficticios al mercado real.

La aportación es un cambio de estrategia comprobado y persistente, no simplemente
recordar el nombre del usuario. No garantiza que toda propuesta sea mejor. El coste
de practicar y comparar también se cuenta; dos fechas no bastan para afirmar que el
sistema supera siempre a otros buscadores.

## Defensa breve: qué tenemos y por qué usar un agente

> ViajeSIBI es un asistente de búsqueda con autonomía limitada. Le doy condiciones,
> no un destino. El modelo propone una consulta, las herramientas devuelven precios
> y el modelo decide el siguiente paso. Python comprueba los importes y las restricciones.
> Se conserva la opción encontrada aunque una consulta posterior sea peor.
>
> El valor que buscamos es recuperar una búsqueda que no funciona: cambiar una opción
> tras conocer el coste conjunto de vuelo y alojamiento. Lo medimos frente al mismo modelo
> con un plan fijado al principio, con los mismos datos y límite de intentos. No damos por
> hecho que gane: mostramos éxito, coste, consultas y errores.
>
> Hay memoria persistente de prioridades confirmadas y un laboratorio de aprendizaje de
> estrategias. En el laboratorio otro rol de Qwen3 propone un cambio a partir de repeticiones;
> Python lo prueba antes de adoptarlo. Esto no modifica los pesos del modelo.

### Preguntas que puede hacer el profesor

| Pregunta | Respuesta defendible |
| --- | --- |
| ¿Por qué no basta un chatbot? | Una respuesta sin consultas no comprueba las ofertas. Aquí se ejecutan herramientas y se vuelve a decidir según sus resultados. Un chatbot que haga ese mismo ciclo también sería agéntico. |
| ¿Qué decide la IA y qué está programado? | Qwen3 elige rutas y fechas. Python limita las acciones, propone un orden de exploración, combina ofertas y verifica precios. Las alternativas de aeropuerto y la relajación autorizada tienen reglas explícitas. |
| ¿Cuántos agentes hay? | Un planificador en la búsqueda y un rol de mejora en el laboratorio. Comparten Qwen3. Vuelos, hoteles, SQLite y validadores son herramientas o componentes, no cuatro agentes adicionales. |
| ¿En qué mejora a Booking? | No hemos hecho esa comparación. El objetivo es delegar una búsqueda con destino abierto, no sustituir una plataforma de reservas. |
| ¿Aprende solo? | Recuerda experiencia. Sugiere fijar el aeropuerto tras rechazos repetidos, con confirmación. El laboratorio ensaya políticas y solo guarda las que superan las pruebas. No aprende automáticamente cualquier preferencia ni garantiza que mejore. |
| ¿Son datos reales? | Planificar y comparar consultan SerpApi. Demostraciones simuladas y aprendizaje usan datos ficticios claramente identificados. Una búsqueda guardada conserva la fecha de su consulta. |
| ¿Respeta mis gustos? | Se mantienen en las instrucciones, pero falta verificar los gustos libres con fuentes específicas. No debemos presentar buena cerveza o playa como hechos comprobados por la API de hoteles. |
| ¿Qué limita la autonomía? | Presupuesto y margen autorizado, fechas permitidas, filtros, número de intentos y validación de respuestas. Nunca compra ni reserva automáticamente. |
| ¿Ya se ha demostrado que es mejor? | Los informes muestran los resultados de cada versión. Los empates y derrotas se conservan. Hace falta una evaluación independiente con datos reales para afirmar superioridad general. |

### Presentación en cinco minutos

1. **Demostraciones → Defender el proyecto**: explica las partes y el ciclo.
2. Abre un informe completo y muestra los resultados de todos los casos, no solo uno favorable.
3. En una comparación guardada, sigue una observación, la siguiente decisión y su resultado.
4. En **Aprendizaje**, muestra experiencia, propuesta y decisión de adoptar/rechazar. Si no se
   adoptó nada, no afirmes que el sistema ya aprendió una estrategia mejor.
5. Cierra con la limitación principal: falta demostrar generalización y verificar gustos libres.
   Propón una evaluación futura con consultas reales archivadas y casos nuevos fijados por adelantado.

## Resultado nuevo: experiencia validada el 11 de noviembre

En el [experimento completo](resultado_aprendizaje_2026-11-11_revision.json), Qwen3
propuso priorizar Barcelona a partir de dos viajes comparables. En las fechas reservadas
15 y 22 de febrero, ambas estrategias encontraron un viaje de 480 EUR. Sin memoria
se hicieron 8 consultas y 2 llamadas al modelo por viaje; con memoria, 4 y 1.
La política superó el criterio y quedó guardada en SQLite.

Puedes decir: «En estos dos casos, usar experiencia redujo a la mitad las consultas sin
empeorar el precio». No digas «siempre consigue viajes más baratos» ni «supera a Booking».
Prepararlo costó 16 consultas de práctica y 24 de validación, todas ficticias, además de
11 llamadas al modelo en total. No es un ahorro neto desde el primer uso. Las fechas
tienen patrones semanales repetidos y los casos se usaron durante el desarrollo: falta
comprobar la generalización con otros casos y ofertas reales.
