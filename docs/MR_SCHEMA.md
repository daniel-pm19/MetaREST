# Contrato de Relación Metamórfica (MR) — v1.0

Fuente de verdad: [`backend/app/models/mr.py`](../backend/app/models/mr.py).
JSON Schemas exportados: [`docs/schemas/`](schemas/) (se regeneran con `cd backend && python -m scripts.export_mr_schema`).
Ejemplos válidos (verificados por los tests): [`docs/mr_examples/`](mr_examples/).

> Cambiar este contrato afecta al pipeline, la API y el frontend. Acordarlo con Daniel antes del push
> y regenerar los schemas en el mismo commit.

## 1. Idea general

Una MR es **ejecutable**: el LLM no devuelve texto libre, sino un objeto `MRSpec` con:

```
source  ──(transformaciones)──▶  followup_1 … followup_n     (n = 1..4)
   │                                   │
   └── selector JSONPath ──▶ S         └── selector JSONPath ──▶ F1 … Fn
                         relación(S, F1..Fn) debe cumplirse
```

El ejecutor arma las peticiones concretas con `MRSpec.instances()`, las envía contra la SUT,
aplica los selectores a los cuerpos de respuesta y evalúa la relación.

## 2. `MRSpec` (lo que genera el LLM)

| Campo | Tipo | Notas |
|---|---|---|
| `title` | str (3–120) | Título corto, en español |
| `description` | str (3–1000) | Qué propiedad verifica |
| `source` | `RequestSpec` | Petición fuente con valores concretos |
| `followups` | `FollowupSpec[]` (1–4) | Peticiones derivadas de la fuente |
| `relation` | `RelationSpec` | Qué debe cumplirse entre las respuestas |
| `transformation_logic` | str (3–500) | Texto legible: cómo cambia la entrada (equivale al campo del paper) |
| `expected_relation` | str (3–500) | Texto legible: qué debe cumplirse (equivale al campo del paper) |
| `rationale` | str (3–1000) | Qué fallo podría revelar y por qué |
| `input_variants` | `InputVariant[]` (0–2) | Instancias de entrada extra; se mezclan sobre los params de `source` |

No se aceptan campos extra (`additionalProperties: false`).

### `RequestSpec`

| Campo | Tipo | Notas |
|---|---|---|
| `method` | `"GET" \| "HEAD"` | Por defecto `GET`. **Nunca métodos que modifiquen la SUT** |
| `path` | str, empieza con `/` | Plantilla OpenAPI, p. ej. `/items/{id}` |
| `path_params` | `{nombre: escalar}` | Exactamente un valor por cada `{placeholder}` del path |
| `query_params` | `{nombre: escalar \| escalar[]}` | |

Escalar = `string | integer | number | boolean`. La URL base y las credenciales no forman parte de
la MR: el ejecutor las toma del proyecto y del `.env`.

### `FollowupSpec`

| Campo | Tipo | Notas |
|---|---|---|
| `method` | `"GET" \| "HEAD"` | Por defecto `GET` |
| `path` | str opcional | Endpoint destino (*target_endpoint*). Si se omite, usa el path de la fuente |
| `transformations` | lista (0–5) | Se aplican en orden |

**Cómo se deriva el follow-up** (`derive_followup`):
1. Se copian los `query_params` y `path_params` de la fuente.
2. Se aplican las transformaciones en orden.
3. Se usa `followup.path` (o el de la fuente) y se conservan solo los `path_params` que ese path usa.
4. Si falta algún placeholder, la MR es **no ejecutable**.

## 3. Catálogo de transformaciones (cerrado)

| `op` | Campos | Efecto | Error si… |
|---|---|---|---|
| `set_param` | `param`, `value`, `location` (`query`\|`path`, def. `query`) | Asigna o sobrescribe el valor | se pone una lista en un parámetro de path |
| `remove_param` | `param` | Quita un parámetro de query | no existe en la fuente |
| `add_param` | `param`, `value` | Agrega un parámetro de query nuevo | ya existe (usar `set_param`) |
| `scale_param` | `param`, `factor` (>0, ≠1), `location`, `round_to_int` (def. `true`) | `valor × factor`; si el original es entero, se redondea | no existe o no es numérico |
| `append_to_param` | `param`, `value`, `separator` (def. `" "`) | String: `valor + sep + value`; lista: agrega el elemento | no existe o no es string ni lista |
| `move_param` | `param`, `from_location`, `to_location`, `to_param` (opcional) | Mueve un valor, p. ej. `?category=x` → `/categories/{category}` | no existe en el origen; lista hacia path |

## 4. Catálogo de relaciones (cerrado)

`S` = selección sobre la respuesta fuente y `Fi` = selección sobre el follow-up *i*.
Los selectores son JSONPath (`$.results[*].id`, `$.total`). `followup_selector` toma por defecto
el valor de `source_selector`. Para las operaciones de conjunto, cada elemento se canonicaliza
como JSON con claves ordenadas, así que se pueden comparar objetos completos.

| `type` | Se cumple si… | Follow-ups | Opciones |
|---|---|---|---|
| `equality` | `Fi == S` (mismos elementos, mismo orden) | ≥1 | — |
| `equivalence` | `Fi == S` como multiconjuntos (sin importar el orden) | ≥1 | — |
| `subset` | `set(Fi) ⊆ set(S)` (`followup_in_source`) o `set(S) ⊆ set(Fi)` (`source_in_followup`) | ≥1 | `direction` **obligatorio** |
| `disjoint` | `S, F1…Fn` disjuntos dos a dos | ≥1 | — |
| `complete` | `set(S) == ⋃ set(Fi)` | **≥2** | — |
| `difference` | `set(S) \ set(F1) == set(F2)` | **exactamente 2** | — |
| `count_leq` | `m(Fi) ≤ m(S)` (`followup_in_source`) o `m(S) ≤ m(Fi)` (`source_in_followup`) | ≥1 | `direction` **obligatorio**; `measure`: `count` (nº de elementos, por defecto) o `value` (el selector debe devolver un único número, p. ej. `$.total`) |
| `same_order` | Los elementos comunes a `S` y `Fi` aparecen en el mismo orden relativo | ≥1 | — |

`direction` solo se permite en `subset` y `count_leq`; `measure`, solo en `count_leq`.

## 5. Veredictos de ejecución

| Veredicto | Significado |
|---|---|
| `pass` | La relación se cumplió en todas las instancias |
| `violation` | Se rompió en al menos una instancia, así que hay un **posible fallo** en la SUT |
| `error` | La petición falló, la respuesta no fue 2xx o JSON válido, el selector apunta a un campo que no existe, o la relación no se pudo evaluar (p. ej. `measure=value` sin un único número). Un arreglo existente pero vacío **no** es error: la relación se evalúa y, si todas las selecciones están vacías, el mensaje lo marca como evidencia débil |
| `skipped` | No se ejecutó |

El veredicto global se agrega con la prioridad `violation > error > pass` (`ExecutionResult.aggregate`).

## 6. `MRCandidate` (estado en el pipeline, se guarda en Mongo)

| Campo | Notas |
|---|---|
| `id`, `project_id`, `run_id`, `schema_version` | |
| `spec` | `MRSpec`, o `null` si la salida del LLM no pasó la validación |
| `raw_output` | Item original del LLM cuando `spec` es `null` (sirve para RQ1) |
| `provenance` | `provider`, `model`, `prompt_version`, `generated_at` |
| `scores` | `semantic_validity` y `fault_revealing` (cada uno con `rules_passed`, `rule_violations`, `llm_score`, `llm_reason`, `score`), `max_similarity`, `combined` |
| `filter_result` | `passed`, `stage`, `reason`, `detail`, `duplicate_of` |
| `execution` | `verdict`, `instances[]` (evidencia HTTP de la fuente y los follow-ups), `executed_at` |
| `status` | `pending_review` → `accepted` \| `rejected`, o `discarded` (por el filtro, estado final) |

Motivos de descarte y etapa del filtro a la que pertenecen:

| `reason` | `stage` | Cuándo |
|---|---|---|
| `not_executable` | `schema` | Falló la validación de `MRSpec` |
| `invalid_semantics` | `semantic` | El OpenAPI no respalda la MR (reglas o chequeo LLM) |
| `low_fault_revealing` | `fault_revealing` | Es trivial, tautológica o queda por debajo del umbral |
| `redundant` | `diversity` | Es demasiado similar a una MR con mejor score (`duplicate_of` obligatorio) |

Invariantes que el modelo valida:
- Si el filtro descartó la MR, `status` es `discarded`, y viceversa.
- Si `spec` es `null`, el motivo de descarte es `not_executable`.

La decisión del QA (aceptar o rechazar con justificación) no vive en el candidato sino en la colección
append-only `decisions`. El candidato solo refleja el `status` resultante.

## 7. Uso en cada módulo

- **Generador (Daniel)**: pide la salida con *structured outputs* (`output_config.format`), no con tool use
  forzado (Sonnet 5.5 y Opus 5.5 lo rechazan con 400). El esquema enviado es `MRGenerationOutput`
  adaptado por `app/pipeline/wire.py`: el API no admite mapas libres ni restricciones como `pattern` o
  `maxLength`, así que `query_params`/`path_params` viajan como listas `[{name, value}]` y se convierten de
  vuelta antes de validar. Las restricciones eliminadas las sigue aplicando Pydantic. La salida se valida
  **ítem por ítem** con `parse_generated_relations()`, de modo que una MR mal formada no descarta todo el
  lote y los rechazos quedan como `not_executable`.
- **Ejecutor (Daniel)**: llama a `spec.instances()` para obtener los pares `(fuente, [follow-ups])`,
  hace las peticiones con httpx, aplica los selectores con `jsonpath-ng` y evalúa la relación según la tabla del §4.
- **Filtros (Daniel)**: llenan `scores` (`semantic_validity`, `fault_revealing`, `combined`, `max_similarity`) y
  `filter_result`. Detalles y umbrales en [`LLM.md`](LLM.md).
- **Orquestador (Daniel)**: `app.pipeline.orchestrator.run_pipeline()` devuelve todas las `MRCandidate` del run y
  un `RunReport` (estado, tiempos, conteos y tokens por etapa). `on_progress` recibe el reporte cada vez que una
  etapa empieza o termina, para actualizar el run en Mongo.
- **Backend (Nestor)**: llama a `run_pipeline()` desde una background task, guarda `PipelineSettings` como
  snapshot en el run, el `RunReport` en el run y cada `MRCandidate` en un documento Beanie (colección `candidates`). Las
  transiciones `pending_review → accepted/rejected` solo ocurren vía `POST /candidates/{id}/decision`.
- **Frontend (Isaac)**: los tipos salen de `/openapi.json`. Mientras tanto, los ejemplos de
  `docs/mr_examples/candidates/` sirven como mocks (MSW).

## 8. Supuesto de los ejemplos (API demo)

Los ejemplos asumen que la API demo expone `GET /search` con los parámetros `q`, `limit`, `page`,
`sort` (`id_asc`, `price_asc`, `price_desc`) y `category`, y que responde
`{"total": int, "results": [{"id": int, ...}]}`. **Nestor**: si `sut-demo` termina con otra forma,
hay que actualizar los ejemplos en el mismo commit.
