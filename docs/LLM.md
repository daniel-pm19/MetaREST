# Capa LLM: decisiones de configuración

Código: [`backend/app/pipeline/llm/`](../backend/app/pipeline/llm/), [`generator.py`](../backend/app/pipeline/generator.py),
[`wire.py`](../backend/app/pipeline/wire.py), [`prompts/`](../backend/app/pipeline/prompts/),
[`filters/`](../backend/app/pipeline/filters/), [`embeddings.py`](../backend/app/pipeline/embeddings.py),
[`orchestrator.py`](../backend/app/pipeline/orchestrator.py).
Responsable: Daniel. Todos los valores se pueden cambiar en `LLMSettings` (el Admin los edita desde la colección
`settings`). Lo que **no** se puede cambiar desde ahí son las reglas de seguridad del §4.

## 1. Valores por defecto

| Parámetro (`LLMSettings`) | Valor | Rango permitido |
|---|---|---|
| `provider` | `anthropic` | `anthropic` · `gemini` (`openai` es un stub que falla con un mensaje claro) |
| `generation_model` | `claude-sonnet-5-5` (Gemini: `gemini-4-hydrogen`) | cualquier id de modelo |
| `generation_effort` | `medium` | `low` · `medium` · `high` · `xhigh` · `max` |
| `generation_max_tokens` | 32 000 | 1 024 – 128 000 |
| `verification_model` | `claude-haiku-5-5` (Gemini: `gemini-3.5-flash-lite`) | cualquier id de modelo |
| `verification_effort` | `low` (Gemini: `medium`, D15) | igual que arriba |
| `verification_max_tokens` | 4 000 | 256 – 128 000 |
| `max_candidates` | 20 | 1 – 50 |
| `enable_fallbacks` | `true` | — |
| `timeout_seconds` | 600 | > 0 |
| `max_retries` | 2 | 0 – 10 |
| `requests_per_minute` | sin límite (Gemini: 12) | 1 – 10 000 por modelo; `null` = sin límite (nivel de pago) |

Filtros (`FilterSettings`, también editables por el Admin):

| Parámetro | Valor | Notas |
|---|---|---|
| `semantic_weight` / `fault_weight` | 0.5 / 0.5 | Pesos del score combinado (se normalizan) |
| `min_semantic` | 0.6 | Por debajo: `invalid_semantics` |
| `min_fault_revealing` | 0.5 | Por debajo: `low_fault_revealing` |
| `similarity_threshold` | 0.975 | Coseno ≥ umbral: `redundant` (ver D12) |
| `use_llm_checks` | `true` | `false` = solo reglas |
| `llm_concurrency` | 4 | Chequeos LLM en paralelo |
| `semantic_prompt` / `fault_prompt` | `semcheck_v2` / `faultcheck_v2` | v1 se conserva para trazabilidad (D15) |
| `embedding_model` | `BAAI/bge-small-en-v1.5` | fastembed (ONNX), ~67 MB |

## 2. Decisiones

### D1. Generación con Claude Sonnet 5.5

- **Decisión**: `claude-sonnet-5-5` genera las MRs candidatas.
- **Por qué**: es la etapa que más exige del modelo (leer el contexto del OpenAPI y producir objetos estructurados
  válidos), pero se repite en cada run y en los experimentos. Sonnet ofrece un buen equilibrio entre calidad,
  costo y latencia para 20 MRs por run.
- **Alternativa**: `claude-opus-5-5` es el modelo más capaz y la recomendación general de Anthropic. Si la tasa de
  MRs no ejecutables (RQ1) es alta con Sonnet, se cambia `generation_model` sin tocar código.
- **Trazabilidad**: el modelo que respondió de verdad queda en `provenance.model` de cada candidata (ver D6), así que
  los experimentos pueden comparar modelos.

### D2. Verificación con Claude Haiku 5.5

- **Decisión**: `claude-haiku-5-5` hace los chequeos LLM de los filtros (validez semántica y potencial de revelar
  fallos).
- **Por qué**: son preguntas cortas (una MR y el contexto, devuelve un score 0–1 y una razón) y hay hasta dos
  por candidata en cada run. Un modelo rápido y barato mantiene bajo el costo del filtro.
- **Limitación**: Haiku 5.5 no admite fallbacks del servidor (D6); el proveedor lo detecta y usa el endpoint normal.

### D3. Salida estructurada con `output_config.format`, no con tool use forzado

- **Decisión**: el JSON se pide con *structured outputs* (`output_config: {format: {type: "json_schema", schema}}`).
- **Por qué**: forzar una herramienta (`tool_choice` `any`/`tool`) devuelve 400 en Sonnet 5.5 y Opus 5.5. Esto
  reemplaza lo que decía el plan original ("vía tool use").
- **Consecuencia**: el API no admite mapas libres ni restricciones como `pattern`, `minLength` o `maxItems`.
  [`wire.py`](../backend/app/pipeline/wire.py) adapta el esquema: `query_params`/`path_params` viajan como listas
  `[{name, value}]`, `oneOf` pasa a `anyOf` y se quitan las palabras clave no soportadas. Pydantic sigue aplicando
  todas las restricciones al validar, ítem por ítem, así que el contrato de [`MR_SCHEMA.md`](MR_SCHEMA.md) no cambia.

### D4. Esfuerzo `medium` (generación) y `low` (verificación); sin `temperature` ni `thinking`

- **Decisión**: se usa `output_config.effort` para controlar cuánto razona el modelo. No se envían `temperature` ni
  parámetros de `thinking`.
- **Por qué**: `effort` es el control recomendado en los modelos actuales. `medium` da MRs razonadas sin disparar la
  latencia; `low` basta para un score corto. Subir a `high` es la primera palanca si la calidad no alcanza.
- **Nota**: sin `temperature` fija, dos runs con la misma entrada pueden diferir. Por eso cada run guarda su snapshot
  de configuración y los experimentos reportan varias corridas.

### D5. `max_tokens` 32 000 / 4 000, con streaming

- **Decisión**: techo de 32 000 tokens de salida para generar y 4 000 para verificar. Las peticiones van por
  streaming y se recogen con `get_final_message()`.
- **Por qué**: 20 MRs con sus textos en español pueden ocupar varios miles de tokens; el techo deja margen para que no
  se corte la salida. El streaming evita los timeouts HTTP con valores altos. Solo se cobran los tokens generados,
  no el techo.
- **Si se corta** (`stop_reason = max_tokens`): el run no se cae; queda un aviso y se conservan las MRs que se
  alcanzaron a validar.

### D6. Fallbacks del servidor activados

- **Decisión**: con `enable_fallbacks = true`, en los modelos que lo admiten se envía `fallbacks: "default"` con la beta
  `server-side-fallback-2026-07-01`. Si el modelo se niega a responder, el servidor reintenta con otro modelo.
- **Por qué**: los OpenAPI son datos no confiables; un texto raro en una descripción no debería tumbar un run entero.
- **Trazabilidad**: `LLMResponse.model` y `fallback_used` registran qué modelo respondió, para no mezclar modelos en
  los resultados sin saberlo.
- **Desactivar**: `enable_fallbacks = false`, o `--no-fallbacks` en `scripts/smoke_generate.py`.

### D7. Máximo 20 candidatas por run

- **Decisión**: `max_candidates = 20` (el plan proponía 30).
- **Por qué**: controla el costo y el tiempo de revisión del QA. Con 3 APIs y varios runs por API para RQ1–RQ4, 20
  candidatas dan suficientes datos antes y después del filtro. El tope duro es 50.

### D8. Prompt en inglés, textos de salida en español

- **Decisión**: las instrucciones de [`gen_v1.system.j2`](../backend/app/pipeline/prompts/gen_v1.system.j2) están en
  inglés; los campos que lee el QA (`title`, `description`, `transformation_logic`, `expected_relation`, `rationale`)
  se piden en español.
- **Por qué**: los nombres de campos, operaciones y relaciones del contrato están en inglés y el modelo los sigue con
  más precisión así; la UI es en español.
- **Versionado**: cada candidata guarda `provenance.prompt_version` (`gen_v1`). Cambiar el prompt implica crear
  `gen_v2`, no editar `gen_v1`, para que los resultados sigan siendo comparables.

### D9. Timeout de 600 s y 2 reintentos

- **Decisión**: el SDK reintenta automáticamente 2 veces los errores transitorios (429, 5xx, conexión).
- **Errores**: se traducen a `LLMProviderError` con `retriable` y un mensaje en español (credenciales, petición
  inválida, límite de uso, error del servidor), que el orquestador guarda en el run.

### D10. Filtros: reglas primero, LLM después

- **Decisión**: cada criterio (validez semántica y potencial de revelar fallos) corre primero reglas deterministas
  en Python y solo si pasan hace el chequeo LLM. Si una regla falla, el score es 0 y la MR se descarta sin gastar
  tokens; el detalle del descarte lista las reglas violadas en español.
- **Reglas semánticas** (contra el OpenAPI): el endpoint y los parámetros existen; tipos, `enum`, mínimo y máximo
  se respetan **en las peticiones ya derivadas** (incluye follow-ups y variantes); los parámetros obligatorios
  siguen presentes; los selectores apuntan a campos de la respuesta; las relaciones de conjunto usan selectores
  que devuelven colecciones; `measure=value` usa un único número; no se usa HEAD (no tiene cuerpo).
- **Reglas de potencial de fallo**: un follow-up idéntico a la fuente es tautológico (salvo en `equality` y
  `equivalence`, donde comprueba determinismo); contar un único valor con `count_leq` es trivial.
- **Score**: reglas violadas → 0; reglas OK + LLM → el score del LLM; reglas OK sin LLM → 1.0. Combinado =
  promedio ponderado de ambos criterios.

### D11. Un chequeo LLM fallido no tumba el run

- **Decisión**: si el chequeo de una MR falla (error del proveedor, rechazo o salida inválida), esa MR queda con
  el resultado de las reglas (score 1.0), `llm_reason` explica el fallo y el run registra un aviso.
- **Por qué**: es preferible que el QA vea una MR más a perder un run entero por un error transitorio.
- **Ojo para los experimentos**: un run con avisos de chequeos fallidos no es comparable para RQ1; hay que repetirlo.
  `python -m mrexp rq1` lo avisa. Con el nivel gratuito de Gemini esto pasaba en masa por los 429 (13-nov): de ahí
  el límite en el cliente de D15.

### D12. Diversidad con firma estructural y umbral 0.975

- **Decisión**: se embebe una **firma** de la MR (relación, selectores, endpoint, nombres de parámetros y
  transformaciones), no su texto libre. Los valores concretos de la fuente no entran: la misma MR con `q=jazz`
  o `q=rock` prueba la misma propiedad. Selección greedy por score combinado; las que superan el umbral frente a
  una ya elegida quedan como `redundant` con `duplicate_of`.
- **Por qué la firma**: es independiente del idioma (el modelo `bge-small` es de inglés y los textos están en
  español) y no depende de cómo redactó el LLM.
- **Calibración del umbral** (bge-small sobre los ejemplos de `docs/mr_examples/specs` y variantes):

  | Pares | Similitud |
  |---|---|
  | MRs distintas | 0.83 – 0.93 |
  | Misma transformación, otra relación | 0.969 |
  | Misma MR con otros valores (factor, categoría, orden invertido) | 0.98 – 0.999 |

  0.975 separa ambos grupos en esta muestra. El margen es chico, así que hay que reajustarlo con MRs reales de las
  3 APIs antes del Hito M3.

### D13. Orquestador

- `run_pipeline()` corre extracción → generación → semántica → potencial de fallo → diversidad → ejecución y
  devuelve **todas** las candidatas (incluidas las descartadas, que hacen falta para RQ1 y RQ2) y un `RunReport`
  con estado, duración, conteos y tokens por etapa.
- Los fallos esperados (spec inválida, proveedor caído, rechazo) no lanzan excepción: quedan en `report.error`
  y las etapas siguientes se marcan como `skipped`.
- Las MRs descartadas no se ejecutan. Para RQ2 (¿alguna redundante detectaba un fallo que las elegidas no?),
  `python -m mrexp mutants --select all` (en `experiments/`) las ejecuta aparte.

### D14. Proveedor Gemini como alternativa

- **Decisión**: `GeminiProvider` con el SDK oficial `google-genai` (`client.aio.models.generate_content`).
  Con `provider = "gemini"`, los modelos por defecto pasan a `gemini-4-hydrogen` (generación) y
  `gemini-3.5-flash-lite` (verificación), salvo que se fijen explícitamente.
- **Por qué**: Google AI Studio tiene un nivel gratuito sin tarjeta; la suscripción Claude Pro no incluye API.
- **Modelos**: la documentación de Gemini recomienda Hydrogen o 3.5 Flash-Lite para proyectos nuevos.
  `gemini-4-argon` razona mejor (opción si el nivel gratuito lo incluye). Los `gemini-2.5-*` están deprecados.
- **Salida estructurada**: `response_mime_type="application/json"` + `response_json_schema`. Se envía el mismo
  esquema de `wire.py` con `const` convertido a `enum` de un valor (Gemini no documenta `const`). Pydantic valida
  igual que con Claude.
- **Esfuerzo**: `effort` → `thinking_level` (`low`, `medium`, `high`; `xhigh`/`max` → `XHIGH` solo en Hydrogen,
  `HIGH` en el resto). Sin `temperature` (los modelos Gemini 4 la ignoran).
- **Corte y rechazo**: `finish_reason` `MAX_TOKENS` → truncado; `SAFETY`, `PROHIBITED_CONTENT`, `RECITATION`, etc.
  o un `block_reason` del prompt → rechazo. Los reintentos de 408/429/5xx los hace el SDK.
- **Sin fallbacks del servidor**: `enable_fallbacks` solo aplica a Claude.
- **Proveedor de los experimentos: Gemini** (decidido por Daniel el 13-nov-2026: no hay key de Claude). Los
  scripts de smoke usan `--provider gemini` por defecto. El default de la app (`LLMSettings`) sigue en Anthropic;
  el Admin elige Gemini en la configuración. En el paper se reporta Gemini; la procedencia de cada MR guarda
  proveedor y modelo. Revisar en los términos del nivel gratuito si Google usa los datos enviados (solo enviamos
  OpenAPI públicos y MRs, nunca respuestas de la SUT ni datos personales).

### D15. Calibración de la verificación (13-nov-2026): Flash-Lite, esfuerzo `medium`, prompts v2

- **Problema**: en los runs de prueba Flash-Lite daba `semantic = 1.0` a todas las MRs; el filtro no discriminaba.
- **Método** (`python -m mrexp calibrate`, ver `experiments/README.md`): las MRs reales de los smoke runs de
  PokeAPI y Crossref que pasan las reglas y dan `pass` contra la API real son **válidas** (17). A cada una se le
  aplica un mutante plausible pero incorrecto (dirección invertida o relación cambiada, con el texto reescrito
  para que coincida); los que pasan las reglas y dan `violation` contra la API real son **inválidos** (13). Las
  etiquetas salen de la ejecución, no del LLM. El conjunto es de los smoke runs, no de los runs de RQ1.
- **Resultados** (`experiments/results/calib_calibration.csv`):

  | Verificación | AUC semántico | Válidas conservadas | Inválidas eliminadas | Tokens |
  |---|---|---|---|---|
  | Flash-Lite `low`, `semcheck_v1` | 0.85 | 17/17 | 9/13 | 119k |
  | Flash-Lite `low`, `semcheck_v2` | 0.92 | 17/17 | 11/13 | 137k |
  | **Flash-Lite `medium`, `semcheck_v2`** | **1.00** | **17/17** | **13/13** | 160k |

  Las puntuaciones salen binarias (0 o 1), así que el umbral da igual entre 0.5 y 0.9: `min_semantic` se queda en
  0.6. Hydrogen y 3.5 Flash también separaron bien en la primera corrida parcial, pero el nivel gratuito les da
  20 peticiones/día: no alcanzan para verificar (≈ 40 chequeos por run).
- **Causa de los fallos de v1**: el prompt de los chequeos solo nombraba las relaciones. Flash-Lite leía `disjoint`
  como «las páginas entre sí» (el ejecutor exige que también la fuente sea disjunta) e ignoraba `direction`.
  `semcheck_v2`/`faultcheck_v2` copian las definiciones exactas de `gen_v1` y piden juzgar el JSON, no el título.
- **Límite de peticiones**: el nivel gratuito permite 15 peticiones/min en Flash-Lite, 20/día en Hydrogen y en
  3.5 Flash (este además 5/min) y 0 en Argon y Carbon. `RateLimitedProvider` espacia las peticiones por modelo (`requests_per_minute`,
  12 por defecto con Gemini) y reintenta un 429 por minuto tras el `retryDelay` que indica Google. Un 429 por día
  falla de inmediato con «cuota diaria agotada… se reinicia en ~N h».
- **Límites de la calibración**: 30 MRs, una sola corrida por configuración, y los mutantes pueden ser más fáciles
  que los errores reales del generador. El criterio de potencial de fallo no se calibró: no hay etiquetas
  objetivas, y las válidas puntúan 0.7–1.0, por encima de `min_fault_revealing` (0.5). RQ1 mide el filtro de
  verdad sobre las candidatas etiquetadas a mano.

## 3. Pendiente de verificar con el API real

Antes: copiar `backend/.env.example` a `backend/.env` y poner la key de la Claude Console (la suscripción Claude
Pro no incluye acceso al API) o la de Google AI Studio (`GEMINI_API_KEY`, con `--provider gemini`). Los scripts `smoke_*` leen ese archivo solos. Sin key, el run termina con
`Anthropic: falta ANTHROPIC_API_KEY` en vez de fallar con un error interno.

Los tests usan `FakeLLMProvider` y un cliente SDK falso; no llaman a Claude. Falta comprobar con una llamada real:

1. Que el API acepta el esquema adaptado por `wire.py` (`anyOf`, `const`, `$ref`).
2. Que `fallbacks: "default"` se acepta junto con `output_config`. Si da 400, correr con `--no-fallbacks` y
   reportarlo a Daniel.

```bash
cd backend && uv run --no-project --python 3.12 --with 'pydantic>=2.9' --with httpx --with jsonpath-ng \
  --with pyyaml --with jinja2 --with anthropic python -m scripts.smoke_generate tests/fixtures/openapi_search.yaml -n 5
```

Prueba del pipeline completo (generación + chequeos con Haiku + embeddings; descarga el modelo la primera vez):

```bash
cd backend && uv run --no-project --python 3.12 --with 'pydantic>=2.9' --with httpx --with jsonpath-ng \
  --with pyyaml --with jinja2 --with anthropic --with fastembed python -m scripts.smoke_pipeline \
  tests/fixtures/openapi_search.yaml -n 8
```

Los scripts usan Gemini por defecto: agregar `--with google-genai` (y `--provider anthropic` para Claude).

**Verificado con Gemini real (13-nov-2026, `gemini-4-hydrogen` + `gemini-3.5-flash-lite`)**: el API acepta el
esquema y los `thinking_level` usados. Resultados de las pruebas (salidas en `experiments/raw/`, no versionadas):

| Spec | MRs | Tras el filtro | Ejecución | Tokens | Tiempo de generación |
|---|---|---|---|---|---|
| Fixture `openapi_search.yaml` | 8 | 8 | sin SUT real; contra el SUT falso: 0 falsos positivos, 3 de 4 fallos detectados | 33k | 33 s |
| PokeAPI | 10 | 9 (1 `invalid_semantics`) | 9 `pass` | 46k | 37 s |
| Crossref | 8 | 7 (1 `redundant`) | 7 `pass` (85 s a 1 req/s) | 68k | 38 s |

Hallazgo: Gemini omitía `source_selector` (opcional en el contrato, por defecto `$`) en 4 de 10 MRs, que luego se
descartaban. Ahora `wire.py` lo exige en el esquema que recibe el LLM (`WIRE_REQUIRED`); el contrato no cambia.
Con Claude sigue pendiente la prueba real (falta key).

## 4. Reglas fijas (no configurables)

- Las API keys van en `backend/.env` (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) y las lee cada SDK; nunca se guardan en
  `settings` ni en Mongo.
- El texto del OpenAPI se sanea, se trunca y va delimitado en `<api_spec>`; los intentos de cerrar el delimitador se
  neutralizan.
- Las respuestas de la SUT nunca se envían al LLM; los chequeos reciben solo el OpenAPI y la MR, ambos delimitados
  (`<api_spec>`, `<mr>`), porque la MR también la escribió un LLM que leyó el OpenAPI.
- Toda salida del LLM se valida con Pydantic antes de usarse.
- Los tests y la CI nunca llaman al LLM real.

## 5. Para los experimentos

- Proveedor: **Gemini** (`gemini-4-hydrogen` + `gemini-3.5-flash-lite` con esfuerzo `medium` y prompts v2), ver D14
  y D15. Con el nivel gratuito, Hydrogen permite 20 peticiones/día: unos 15 runs por día como máximo (1 generación
  por run más reintentos). No gastar esa cuota en pruebas el día de los experimentos.
- Configuración **congelada** el 13-nov-2026 en `experiments/config/experiment.json` (`PipelineSettings` completo,
  20 MRs por run). Los runs se lanzan con `python -m mrexp run`, que guarda en cada export el sha256 de esa config y
  del spec y el commit. No se cambia durante las corridas; si cambia, se repiten todos los runs.
- Reportar en el paper modelo de generación, modelo de verificación, `effort`, `max_candidates`, versión del prompt y
  cuántas respuestas usaron fallback.
