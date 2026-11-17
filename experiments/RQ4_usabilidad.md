# RQ4 · Usabilidad y esfuerzo de revisión (borrador para el paper)

> Texto para copiar a la sección 7. Todo lo que dice se puede reproducir con el repo. **No contiene ningún puntaje
> SUS**: no se realizó la evaluación con usuarios. `sus/responses_synthetic.csv` es ficticio y existe solo para probar
> `sus/score.py`; no debe citarse como resultado.

## Qué se midió

1. **Tiempos de revisión** de las decisiones registradas (`results/demo_review_times.csv`).
2. **Inspección heurística** de la interfaz de revisión contra las 10 heurísticas de Nielsen, hecha por un
   inspector leyendo el código de `Layout.tsx` y `Review.tsx`, sin ejecutar la aplicación ni observar usuarios.
3. **Pruebas automáticas de accesibilidad** (axe-core sobre la pantalla de inicio de sesión).

El cuestionario SUS (Brooke, 1996) quedó **sin realizar**. El protocolo (`sus/PROTOCOL.md`) y el script de
puntuación están listos para repetirlo con al menos cinco participantes.

## Resultados

### Tiempos de revisión

Un revisor, autor del proyecto, aceptó las 12 MRs que pasaron el filtro en la API demo: 8.1 min en total,
mediana 3.6 s, media 40.6 s, rango de 0.5 s a 3.7 min. Seis decisiones tardaron menos de 1.2 s, tiempo insuficiente
para leer una MR. **Estos tiempos no estiman el esfuerzo de un auditor independiente.** Tampoco hubo rechazos, así que
no se midió el esfuerzo de justificar.

### Inspección heurística

Alcance: lista y detalle de revisión y la barra de navegación. No se inspeccionaron Resumen, Comparar,
Proyectos ni Administración. Severidad 0–4 (4 = catastrófico), asignada por el mismo inspector.

| # | Heurística | Hallazgo | Sev. |
|---|---|---|---|
| 1 | H5 Prevención de errores | **Aceptar no pide confirmación ni se puede deshacer** (el pie del detalle dice que la decisión es definitiva). Una pulsación accidental queda registrada en una auditoría append-only. Los seis tiempos < 1.2 s sugieren decisiones sin lectura. | 3 |
| 2 | H3 Control y libertad | Sin deshacer ni reabrir una MR ya decidida. Es coherente con la auditoría inmutable, pero no hay ventana de arrepentimiento. | 2 |
| 3 | H4 Consistencia / H7 Eficiencia | En escritorio, el selector de proyecto e iteración está en la barra lateral, que se oculta en móvil: allí no se puede cambiar de iteración. | 3 |
| 4 | H7 Flexibilidad | Existen atajos J/K para navegar, pero no para aceptar o rechazar, y su indicación se oculta en pantallas pequeñas. | 1 |
| 5 | H6 Reconocimiento | Las pestañas usan `role="tab"` sin navegación con flechas, como espera el patrón ARIA. | 2 |
| 6 | H2 Lenguaje del usuario | Términos como `expected_relation`, `followup` y los nombres de relación se muestran casi crudos; requieren conocer metamorfismo. | 2 |
| 7 | H8 Diseño minimalista / accesibilidad | Texto auxiliar en `slate-400` sobre blanco (≈ 2.6:1) incumple el contraste AA (4.5:1) en la línea de procedencia y en el hint de atajos. | 2 |
| 8 | H1 Visibilidad del estado | Bien resuelto: indicador de generación en curso, insignias de estado y veredicto, y avisos con `role="alert"`. | — |
| 9 | H9 Recuperación de errores | Bien resuelto: rechazar sin justificación enfoca el campo y explica el motivo. | — |

Limitaciones: un solo inspector, que además es el desarrollador. Las heurísticas se aplican mejor con 3–5 inspectores
independientes, y esto no sustituye la prueba con usuarios.

### Accesibilidad

19 pruebas de Vitest pasan, incluida una de axe-core sobre Login. No cubre contraste ni layout, que jsdom no calcula.
Sigue pendiente la revisión manual en móvil y con lector de pantalla.

## Amenazas a la validez

- Un único revisor, que conoce el sistema y los fallos.
- Sin usuarios independientes, no se puede afirmar nada sobre usabilidad percibida ni sobre el esfuerzo real.
- La inspección es del mismo desarrollador y se centra en la pantalla de revisión.

## Para secciones 8 y 9

- **Conclusión**: la interfaz soporta el flujo completo (revisión con evidencia, justificación obligatoria y
  auditoría), pero su usabilidad con auditores externos no se evaluó.
- **Trabajo futuro**: aplicar el SUS con al menos cinco participantes de perfil QA; añadir confirmación o
  ventana de deshacer al aceptar; hacer accesible el selector de iteración en móvil; corregir contraste y
  navegación por teclado de las pestañas.
