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

La evidencia real se limita a los lugares documentados. Los costes de la demostración siguen siendo simulados y la integración con ofertas reales queda pendiente. El siguiente experimento debe medir si el orden aprendido mejora las propuestas finales del planificador, además de comprobar que cambia la búsqueda.

## Demo de planificación colaborativa

En la interfaz, abre «Probar coordinación y aprendizaje». La demo usa un catálogo de prueba para una persona y dos noches. Los importes y horarios son simulados. El panel compara el mismo coordinador con y sin memoria.

- **Coordinación.** Elige Valencia y un límite de 200 €. Los agentes prueban Barcelona y descartan combinaciones que superan el límite. El plan viable de Zaragoza cuesta 158 €.
- **Reparación.** Elige Valencia y 250 €. Simula la cancelación del transporte. El coordinador conserva el hotel y propone otro tren por un total de 250 €.
- **Aprendizaje.** Con un perfil de demo vacío, guarda una corrección de cocina y una de llegada temprana. Abre otra comparación y repite la corrección de llegada. Con Sevilla y 185 €, el peso adicional puede cambiar la decisión final: a igualdad de señales se elige autobús y cocina por 183 €, mientras que dos señales de llegada frente a una de cocina priorizan tren y hotel por 184 €. Una excepción para este viaje permite llegar tarde sin cambiar el perfil guardado.

Las capas de esta demo deciden mediante reglas explícitas. El planificador del chat usa Qwen3. Las pruebas cubren el rechazo por presupuesto, la reparación y la transferencia de preferencias. La comparación con memoria desactivada mide el efecto de la personalización. Para afirmar una mejora frente a Gemini haría falta repetir el mismo ejercicio con el mismo catálogo y correcciones en ambos sistemas.
