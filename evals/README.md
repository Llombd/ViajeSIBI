# Evaluación comparativa de ViajeSIBI

La pregunta es si las herramientas y las validaciones de ViajeSIBI mejoran la exactitud y el cumplimiento de restricciones frente a una llamada directa a Qwen3.

Ambos modos reciben las mismas consultas y usan el mismo modelo, temperatura y límite de salida por llamada. El modelo directo recibe todos los costes del catálogo y la fórmula de cálculo. El agente puede pedir a Python que consulte y calcule los datos. El agente también tiene sus propias instrucciones y puede hacer varias llamadas al modelo. La comparación mide el sistema completo, sin aislar el efecto de cada componente.

Con Ollama abierto y el modelo `qwen3:4b` instalado, ejecuta desde la raíz del proyecto:

```bash
python3 -B -m evals.comparar
```

Cada línea registra el caso, el modo, la respuesta, el error si lo hubo, el tiempo total y las trazas del agente. Puedes seleccionar un caso con `--caso coste`.

| Caso | Criterio de éxito |
|---|---|
| Coste exacto | Indica 770 EUR para el grupo y 385 EUR por persona en Oporto. |
| Comparación con presupuesto | Identifica Oporto como opción compatible con 800 EUR, excluye Lisboa y compara 770 EUR con 910 EUR. |
| Origen sin cobertura | Explica que faltan datos para León. No da un coste ni cambia el origen sin consentimiento. |

Revisa cada respuesta completa con el mismo criterio. Una respuesta con error, sin conclusión o con un importe contradictorio no pasa. Usa las trazas para explicar cómo se obtuvo una respuesta y registra también la latencia. No cuentes la aparición de una llamada a herramienta como éxito por sí sola.

Esta primera prueba usa un catálogo ficticio para que los valores esperados se puedan comprobar de forma reproducible. Para sostener una conclusión general, amplía el conjunto de casos, repite cada consulta varias veces y separa exactitud, cumplimiento del presupuesto y latencia.

## Primera ejecución con Ollama

Prueba de una ejecución por caso con Qwen3 4B, sobre la versión `748a777`, antes de incorporar SQLite. La corrección aplica el criterio completo de cada fila.

| Caso | Modelo directo | Agente | Tiempo directo / agente |
|---|---|---|---|
| Coste exacto | Correcto: 770 EUR y 385 EUR por persona. | Correcto: consultó la herramienta y mostró ambos importes. | 35,59 s / 15,30 s |
| Comparación con presupuesto | La salida alcanzó el límite antes de concluir. | Parcial: recomendó Oporto por 770 EUR, pero no consultó ni mostró el coste de Lisboa. | 41,98 s / 16,17 s |
| Origen sin cobertura | La salida alcanzó el límite antes de concluir. | Correcto: detectó la falta de datos para León y pidió consentimiento para cambiar de origen. | 49,60 s / 0,01 s |

El modelo directo pasó 1 de 3 casos y el agente pasó 2 de 3. En el caso de presupuesto, el agente acertó la opción compatible, pero la comparación solicitada quedó incompleta. Los dos fallos del modelo directo se deben al límite de salida. Conviene repetir la prueba con un límite mayor y más repeticiones antes de sacar conclusiones sobre exactitud o velocidad. El caso de León se resolvió con una validación previa a la llamada al modelo.

## Demostración de las capas y del aprendizaje

1. **Planificación.** Qwen3 interpreta la consulta y decide qué herramienta invocar.
2. **Datos.** La herramienta filtra el catálogo por las condiciones explícitas. La capa de datos recupera fichas verificadas de SQLite y adjunta su enlace. La cobertura inicial es Oporto, Lisboa y Barcelona, con fichas de la UNESCO.
3. **Preferencias.** Cada valoración explícita se guarda en SQLite. Los votos aportan señales por destino y por categoría de interés. Si se repite una valoración para el mismo destino, se actualiza su valor. El orden de los candidatos compatibles puede cambiar en futuras búsquedas. La validación final mantiene los límites del viaje y comprueba los importes.

Para demostrarlo en un perfil vacío, busca destinos del sur y revisa el orden de los candidatos en «Herramientas y validaciones». Marca Oporto como «Me interesa» en «Preferencias aprendidas», empieza una conversación nueva y repite la consulta. Si el planificador elige buscar destinos, verás el nuevo orden y el perfil en el resultado de la herramienta. La prueba automatizada reproduce el mismo caso con dos instancias del agente y comprueba que Oporto pasa de segundo a primero y que las condiciones y el precio permanecen iguales.

Las valoraciones son del perfil local de la instalación. Se almacenan en `.viajesibi.sqlite3`, excluida de Git. `VIAJESIBI_DB` permite usar otra base de datos. La app guarda las valoraciones explícitas, sin guardar las conversaciones en SQLite. El aprendizaje actual actualiza un perfil que guía las búsquedas y mantiene los pesos de Qwen3. Las capas de datos y preferencias aplican reglas deterministas y Qwen3 toma las decisiones de planificación.

La evidencia real se limita a los lugares documentados. Los costes de esta demostración son simulados. La búsqueda de ofertas reales funciona en la aplicación principal. El siguiente experimento debe medir si el orden aprendido mejora las propuestas finales del planificador, además de comprobar que cambia la búsqueda.

## Demo de planificación colaborativa

Estos escenarios se conservan como pruebas automáticas en `tests/test_plan_colaborativo.py`. Usan costes y horarios simulados para una persona y dos noches y comprueban el coordinador con y sin memoria.

- **Coordinación.** Elige Valencia y un límite de 200 €. Los agentes prueban Barcelona y descartan combinaciones que superan el límite. El plan viable de Zaragoza cuesta 158 €.
- **Reparación.** Elige Valencia y 250 €. Simula la cancelación del transporte. El coordinador conserva el hotel y propone otro tren por un total de 250 €.
- **Aprendizaje.** Con un perfil de demo vacío, guarda una corrección de cocina y una de llegada temprana. Abre otra comparación y repite la corrección de llegada. Con Sevilla y 185 €, el peso adicional puede cambiar la decisión final: a igualdad de señales se elige autobús y cocina por 183 €, mientras que dos señales de llegada frente a una de cocina priorizan tren y hotel por 184 €. Una excepción para este viaje permite llegar tarde sin cambiar el perfil guardado.

Las capas de esta demo deciden mediante reglas explícitas. El planificador del chat usa Qwen3. Las pruebas cubren el rechazo por presupuesto, la reparación y la transferencia de preferencias. La comparación con memoria desactivada mide el efecto de la personalización. Para afirmar una mejora frente a Gemini haría falta repetir el mismo ejercicio con el mismo catálogo y correcciones en ambos sistemas.

## Búsqueda fija frente a búsqueda adaptativa

La prueba `test_comparacion_controlada_con_mismo_numero_de_consultas` simula un conjunto
de ofertas y da a ambos métodos dos consultas. Con 800 € de presupuesto, la lista fija
comprueba dos destinos cuyos mejores totales son 900 € y 850 €. La búsqueda adaptativa
usa el primer resultado para elegir otro destino y encuentra un plan de 650 €.
Es una comprobación controlada del mecanismo, con ofertas y decisión simuladas.
Todavía falta medir el resultado con el modelo y las ofertas reales en varios viajes.

### Piloto con Qwen3 y ofertas ficticias

Desde la raíz del proyecto, con Ollama activo:

~~~bash
.venv/bin/python -B -m evals.evaluar_replanteamiento
~~~

En una ejecución se compararon seis viajes de tres noches para dos adultos, con tres
intentos por método en cada caso. Ambos métodos compartieron la propuesta inicial y el
catálogo. El agente ganó un caso, empató tres y perdió dos.

| Salida | Presupuesto del grupo | Lista fija | Agente adaptativo |
| --- | ---: | ---: | ---: |
| Valencia | 400 € | 450 € | 480 € |
| León | 450 € | 468 € | 468 € |
| Bilbao | 500 € | 458 € | 428 € |
| Madrid | 600 € | 412 € | 412 € |
| Sevilla | 700 € | 522 € | 522 € |
| Barcelona | 350 € | 414 € | 540 € |

Ambos métodos encontraron un viaje viable en tres de seis casos. Desde Bilbao, probar
Sevilla en lugar de Barcelona redujo el mejor total en 30 €. Desde Barcelona, probar
Valencia en otra fecha consumió el intento que la lista fija dedicó a Sevilla, y empeoró
el mejor total. Este piloto mide el efecto sobre el precio con el catálogo ficticio.
Los destinos que elige Qwen3 pueden variar entre ejecuciones.

## Revisión del ciclo de decisión — 9 de noviembre de 2026

Se corrigió la pérdida de resultados parciales, se eliminó el cambio automático de fechas
que podía confundirse con una decisión de Qwen3 y se separó el diagnóstico calculado del
objetivo elegido por el modelo. La revisión devuelve una sola acción validada. El modelo
puede comparar otra opción aunque ya haya un plan asequible; los planes anteriores se conservan.
Los límites de las etapas adicionales se respetan explícitamente.

Durante el desarrollo, una explicación libre de Qwen3 afirmó incorrectamente que 480 €
estaban dentro de 400 €. Esa salida ya no se muestra: el modelo selecciona un código de
objetivo y Python redacta las cifras y las comparaciones. Una prueba reproduce el rechazo.

### Resultado medido, sin selección de casos favorables

Se repitieron los seis casos del piloto anterior, con los mismos datos ficticios,
fechas (1–21 de febrero de 2027), dos adultos y tres noches. Cada método realizó tres
intentos por caso. Qwen3 eligió consultas válidas en las revisiones, pero las rutas y fechas
coincidieron con la lista fija. Resultado: **6 empates, 0 victorias y 0 derrotas**; ambos
métodos encontraron un total dentro del presupuesto en **3 de 6 casos**.

| Origen | Límite del grupo | Mejor total en ambos métodos |
| --- | ---: | ---: |
| VLC | 400 € | 450 € |
| LEN | 450 € | 468 € |
| BIO | 500 € | 458 € |
| MAD | 600 € | 412 € |
| SVQ | 700 € | 522 € |
| BCN | 350 € | 414 € |

El [informe JSON](resultado_revision_2026-11-09.json) incluye trazas, configuración del viaje,
fecha, modelo, duración del caso y huellas SHA-256 del código evaluado. La duración conjunta
por caso fue de 18–34 segundos; no es una comparación de latencia entre los métodos.
Después de esa ejecución se precisó la etiqueta de traza para distinguir confirmar una
consulta pendiente de cambiarla; no cambió la elección de consultas.

Para repetir y guardar otro informe (Ollama necesario, SerpApi no):

```bash
.venv/bin/python -B -m evals.evaluar_replanteamiento --detalle --salida /tmp/evaluacion-viajesibi.json
```

Si Ollama falla, el evaluador conserva el fallo y termina con código distinto de cero.
No elimina casos fallidos del balance. El catálogo sintético tiene precios construidos
mediante fórmulas, no representa la distribución real de precios ni permite generalizar
resultados a ofertas reales.

### Qué se puede enseñar y qué falta demostrar

- **Mecanismo comprobado:** `tests/test_revision_busqueda.py` reproduce con decisiones y
  ofertas simuladas el paso de dos opciones fuera de presupuesto (900 y 850 €) a otra
  de 650 €, cambiando la búsqueda tras observar el coste del alojamiento. Comprueba también
  persistencia de opciones válidas, fechas permitidas, repeticiones, errores y límites.
  Esto demuestra que el mecanismo funciona; no mide la calidad de Qwen3.
- **Modelo real comprobado:** el piloto anterior ejecuta Qwen3 y registra sus decisiones.
  Los seis empates no demuestran una mejora de recomendación. El modelo añade llamadas
  para revisar y puede no aportar una ventaja. No se presenta como superior a otros productos.
- **Demostración interactiva:** `Demostraciones → Comparación simulada` ejecuta ambos modos
  con el mismo formulario, sin API. En los resultados se ve observación → siguiente decisión.
  La comparación real sigue disponible en su propia pestaña y consume cuota de SerpApi.
- **Siguiente evidencia necesaria:** evaluar un conjunto fijado de antemano de búsquedas
  reales (o respuestas reales archivadas) con disponibilidad variable, varios presupuestos
  y filtros. Medir éxito, coste, llamadas y latencia en todos los casos, incluidos empates y
  derrotas. La adecuación a gustos libres necesita además evidencia de lugares/servicios;
  una API de vuelos y hoteles no la verifica.

La suite tras esta revisión tiene 162 pruebas y pasa sin omisiones en el entorno del
proyecto. No se consumieron búsquedas de SerpApi durante esta revisión.

## Resultado útil y consultas evitables — 10 de noviembre

La interfaz distingue conseguir un viaje de encontrar un precio menor que todavía supera
el presupuesto. El nuevo resumen muestra éxito, precio y consultas por separado; no llama
ahorro a la diferencia con un viaje que el usuario no podía aceptar. Las comparaciones
antiguas sin contador muestran datos no registrados, no cero consultas.

Se aplica el descarte previo al hotel a **ambos métodos**, con el mismo límite. Si los vuelos
comprobados ya superan ese límite, se evita la consulta de estancia y se pasa el diagnóstico
a Qwen3. Esto es una optimización de Python, no evidencia exclusiva a favor de un agente.
En la planificación normal se incluye el margen autorizado al decidir ese descarte.

La prueba integrada `test_recuperacion_completa_tras_descartar_vuelo_sin_gastar_consulta_de_hotel`
usa decisiones y ofertas simuladas: la lista comprueba vuelos de 950 y 850 €; el agente
observa el vuelo de 950 € y consulta una alternativa de 350 € de vuelo + 300 € de hotel.
Con 800 € de presupuesto, solo el agente consigue un viaje, pero requiere cinco consultas
frente a cuatro de la lista. Se informa de ambas cosas. Esta prueba no es un resultado empírico de Qwen3.

La prueba de eficiencia con el catálogo ficticio conserva los mismos destinos y pasa de
8 a 6 consultas sin perder ninguna opción dentro del máximo de 200 €. Aísla el efecto
del descarte previo, sin atribuírselo al replanteamiento del modelo.

### Comprobación con Qwen3 real

```bash
.venv/bin/python -B -m evals.evaluar_replanteamiento --comprobar-limite --salida /tmp/limite-viajesibi.json
```

Se ejecutó con origen Madrid, dos adultos, tres noches y 200 € de grupo. Ambos métodos
consultaron Valencia, Sevilla y Bilbao. Cada uno hizo 9 consultas de datos y evitó 3 de
alojamiento porque los vuelos comprobados ya superaban el máximo. Ninguno consiguió un
viaje admisible. Este caso comprueba el límite; **no sustituye el piloto de seis casos ni
demuestra una ventaja del agente**. [Informe completo](resultado_limite_2026-11-10.json).

La suite completa pasa **174 pruebas, sin omisiones**. No se consumió SerpApi.
El [guion de presentación](guion_profesor.md) explica qué puede mostrarse a un público no técnico.

## Laboratorio de experiencia

`aprender_experiencia.py` ejecuta Qwen3 real sobre ofertas ficticias sin SerpApi.
El objetivo es una opción válida desde Valencia para dos adultos, tres noches, cultura
y 500 EUR totales. Práctica: 1 y 8 de febrero de 2027; validación: 15 y 22 de febrero.
No se incorporan los resultados de validación a la memoria. Repetir el experimento no
convierte estas fechas en nuevos casos independientes.

La candidata añade evidencia histórica y reordena los candidatos. Se mide el efecto
conjunto de ambos cambios, no una capacidad aislada del modelo. Se alterna el orden de
ejecución de las estrategias. La validación exige no empeorar precio ni consultas,
resolver ambos casos y mejorar alguna medida; empate significa no adoptar.

Los informes incluyen trazas, consultas, llamadas al modelo y huellas del código.
Se conservan los intentos fallidos y los rechazos. Los patrones semanales del catálogo
limitan la generalización: falta una evaluación independiente con ofertas reales
archivadas antes de afirmar una mejora comercial.

### Repetición del 11 de noviembre de 2026

[Informe completo](resultado_aprendizaje_2026-11-11.json): Qwen3 eligió `mantener`.
No se ejecutó la comparación de una candidata ni se activó una nueva política.
Esto comprueba el registro de experiencia y la decisión de conservar la estrategia;
**no demuestra una mejora de eficiencia**. Se conserva también el intento anterior
con el mismo resultado y el primer intento con un error de propuesta.

Suite verificada: 190 pruebas pasan, sin omisiones. No se consumió SerpApi.

### Revisión funcional y aprendizaje: 11 de noviembre

Se ensayó un protocolo con identificadores de consulta. Los pilotos
`resultado_revision_2026-11-11.json` y `resultado_revision_2026-11-11_exploracion.json`
mostraron una regresión: el modelo insistía en cambiar fechas de la misma ciudad. Se
retiró ese formato y se mantuvo la respuesta estructurada anterior, con validación de
combinaciones pendientes y sugerencias de exploración explícitas. Se conservan ambos
informes desfavorables; no describen la versión final.

`resultado_aprendizaje_2026-11-11_revision.json`: tras aclarar que el rol de mejora
propone un experimento (no lo aprueba), Qwen3 propuso `priorizar_exitos` con evidencia
de Barcelona. En dos casos: precio 480 EUR por viaje en ambas estrategias; consultas
8 → 4 y llamadas al modelo 2 → 1 por viaje. Adoptada. El coste previo fue 40 consultas
ficticias y 11 llamadas al modelo entre práctica, propuesta y validación. Las pruebas
reservadas no se incorporan a memoria, pero se reutilizan durante el desarrollo y el
catálogo tiene periodicidad semanal: esto no es una evaluación independiente de mercado.

Se reforzó la adopción: evidencia repetida existente en SQLite, importes finitos y
dentro del presupuesto, y reutilización exclusiva de la evidencia evaluada.

La revisión posterior conserva una política de exploración explícita: con un total
confirmado se comprueba otro destino; cuando faltan ofertas o impuestos se permiten
otras fechas de esa ciudad. Esto acota el uso de los tres intentos, no asegura que las
otras fechas tengan el mismo precio ni que el destino quede descartado para siempre.
La regla es de Python y no se atribuye al razonamiento del modelo.

La suite tras esta revisión pasa **201 pruebas, sin omisiones**. Las comprobaciones
de interfaz se hacen con Streamlit AppTest, sin APIs. La inspección visual por navegador
no pudo completarse porque la herramienta de navegador agotó su tiempo de espera.

## Equipo de cuatro agentes — 15 de noviembre

La planificación principal y la búsqueda simulada utilizan Coordinación, Destinos,
Transporte y Alojamiento, con Qwen3 y sus historiales separados. El coordinador recibe
los resultados de cada especialista antes de decidir el siguiente encargo.
Transporte decide la ordenación y las salidas cuyo regreso consulta; Alojamiento decide
buscar por precio o valoración, dentro de los filtros ya aplicados.

En la comprobación integrada [resultado_equipo_2026-11-15.json](resultado_equipo_2026-11-15.json)
se ejecutó el formulario con Qwen3 real y el catálogo ficticio, sin SerpApi. El encargo
fue Valencia, dos adultos, 1.000 € de grupo y una opción válida. El equipo encontró
Madrid por 784 € (438 € de vuelo y 346 € de estancia), con cuatro consultas de datos
y diez decisiones del modelo. La traza identifica los cuatro roles.

La prueba automatizada de recuperación obliga a revisar un plan de 900 € (200 € de
vuelo y 700 € de hotel) y encuentra otro de 650 € (350 € y 300 €), con 800 € de
presupuesto. Usa decisiones simuladas para comprobar la transferencia de los costes
entre agentes. La prueba integrada demuestra ejecución del equipo con Qwen3, no
superioridad frente al planificador anterior. La comparación histórica mantiene su
protocolo y sus resultados no deben atribuirse al equipo nuevo.

### Revisión del ciclo de decisiones

El coordinador puede pedir primero estancia o transporte, revisar un componente del
mismo viaje conservando el otro, o pedir al agente de destinos otra ciudad o unas fechas
permitidas distintas. Se recombinan las ofertas ya consultadas. El objetivo económico es
el total del viaje; el orden de consulta no fija para siempre un presupuesto al alojamiento.

Las pruebas automatizadas cubren cambiar la estancia sin repetir vuelos, cambiar vuelos
sin repetir la estancia y volver a Oporto en otra fecha permitida. El coordinador no puede
cerrar por decisión propia sin opciones válidas mientras queden revisiones autorizadas
y presupuesto de consultas. Los límites y las respuestas inválidas pueden cerrar el ciclo.

En la repetición con Qwen3 real y ofertas ficticias, el coordinador eligió Madrid. Transporte
comprobó ambas salidas y Alojamiento consultó dos ordenaciones. El mejor total fue 598 €
con un presupuesto de 600 €, cinco consultas de datos y once decisiones del modelo.
La evidencia completa está en [resultado_equipo_ciclico_2026-11-15.json](resultado_equipo_ciclico_2026-11-15.json).
En esa ejecución no fue necesario cambiar de destino después de obtener el total válido.

## Mejora del equipo y comparación con un agente — 15 de noviembre

Se fijaron antes de revisar la eficiencia tres encargos: Valencia con 600 €, León con
500 € y Bilbao con 700 €, para dos adultos y tres noches, con dos ventanas de marzo.
Cada estrategia dispone de doce consultas de datos y tres combinaciones de destino y
fechas. El planificador único usa las herramientas y también puede revisar sus decisiones.
El equipo dispone además de decisiones separadas para transporte y alojamiento.
Esta comparación evalúa el conjunto de cambios de organización y consultas, no aísla
el número de agentes como única causa.

| Origen | Equipo previo | Equipo revisado | Agente único | Decisiones equipo antes / después | Consultas equipo antes / después |
| --- | ---: | ---: | ---: | --- | --- |
| Valencia | 668 € | 500 € | 470 € | 25 / 21 | 9 / 12 |
| León | 656 € | 584 € | 488 € | 25 / 21 | 8 / 12 |
| Bilbao | 646 € | 574 € | 478 € | 25 / 21 | 9 / 12 |

El equipo pasó de resolver uno a dos encargos dentro del presupuesto. El agente único
resolvió los tres. Ambos ensayos del equipo respetan el mismo máximo de consultas.
La mejora del equipo reduce decisiones y aprovecha más consultas de ofertas, pero no
supera al agente único en estos casos. También se registran los tiempos, que dependen de
la carga del Mac y no se interpretan como una medida independiente de rapidez.

Los resultados y las trazas completos están en
[versión previa](resultado_equipo_antes_2026-11-15.json) y
[versión revisada](resultado_equipo_mejora_2026-11-15.json).
Después de esta medición se priorizó explorar ciudades no visitadas, conservando las otras
fechas como alternativas autorizadas, y se redujo el contexto repetido enviado al modelo.
Estas revisiones posteriores no se atribuyen a los resultados de la tabla.

La pestaña **Comparar IA y agente** permite ejecutar el equipo actual contra un agente con
herramientas. La opción del protocolo anterior se mantiene para reproducir informes antiguos.
La tabla informa de precios, viajes válidos, consultas y decisiones de Qwen3 por método.

La comprobación final de una sola búsqueda, posterior a esas revisiones, está en
[resultado_equipo_final_2026-11-15.json](resultado_equipo_final_2026-11-15.json).
Desde Valencia con 600 € encontró un viaje de 570 €, con 12 consultas y 23 decisiones,
en 84,41 segundos. Es peor que los 500 € de la revisión intermedia y que los 470 €
del agente único en la batería. La traza muestra que Qwen3 volvió a repetir Madrid
en otra fecha pese a recibir la prioridad de explorar otras ciudades. Por tanto,
esa prioridad de exploración no ha demostrado una mejora estable. Se conserva el
resultado desfavorable junto con los demás informes.
