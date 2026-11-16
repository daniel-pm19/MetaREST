# SUS — protocolo (RQ4)

Objetivo: medir la usabilidad de MetaREST con el cuestionario SUS (Brooke, 1996) y los tiempos de revisión del log de decisiones.
Mínimo: **5 participantes** con perfil de QA o desarrollo (idealmente que no hayan participado en el proyecto).

## Sesión (≈ 25 min por persona)

1. Consentimiento verbal: datos anónimos, se puede parar cuando se quiera. Anotar solo un id (`P1`, `P2`…).
2. Crear el usuario con rol **Auditor QA** (Administración → Usuarios) y abrir el proyecto de demostración.
3. Tareas, sin ayuda y en este orden (cronometrar cada una):
   1. Encontrar la iteración actual y decir cuántas MRs están pendientes de revisión.
   2. Abrir una MR, explicar con sus palabras qué verifica y aceptarla.
   3. Rechazar otra MR escribiendo una justificación.
   4. Ver en **Descartadas** por qué el filtro eliminó una MR.
   5. Lanzar una nueva iteración y compararla con la anterior (**Comparar iteraciones**).
4. Cuestionario SUS (abajo) en papel o formulario, **inmediatamente** después.
5. Dos preguntas abiertas: *¿qué fue lo más confuso?* y *¿qué cambiarías primero?*

## Registro

Una fila por persona en `experiments/sus/responses.csv` (columnas `participant,q1..q10,t1..t5_s,notes`). No guardar nombres.
Los tiempos t1..t5 en segundos. Las respuestas q1..q10 van de 1 (totalmente en desacuerdo) a 5 (totalmente de acuerdo).

## Cuestionario SUS (versión en español)

1. Creo que me gustaría usar este sistema con frecuencia.
2. Encontré el sistema innecesariamente complejo.
3. Pensé que el sistema era fácil de usar.
4. Creo que necesitaría el apoyo de una persona técnica para poder usar este sistema.
5. Encontré que las diversas funciones del sistema estaban bien integradas.
6. Pensé que había demasiada inconsistencia en este sistema.
7. Imagino que la mayoría de las personas aprendería a usar este sistema muy rápidamente.
8. Encontré el sistema muy incómodo de usar.
9. Me sentí muy seguro/a usando el sistema.
10. Necesité aprender muchas cosas antes de poder empezar a usar el sistema.

## Puntuación

Ítems impares: `respuesta − 1`. Ítems pares: `5 − respuesta`. Se suman los 10 valores y se multiplica por 2,5 (0–100).
Referencia habitual: 68 es la media; ≥ 80 se considera excelente. Con n pequeño, reportar media, mediana y rango, no solo la media.

```bash
python experiments/sus/score.py experiments/sus/responses.csv
```
