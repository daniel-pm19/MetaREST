# Capa LLM: decisiones de configuración

Código: [`backend/app/pipeline/llm/`](../backend/app/pipeline/llm/), [`generator.py`](../backend/app/pipeline/generator.py),
[`wire.py`](../backend/app/pipeline/wire.py), [`prompts/`](../backend/app/pipeline/prompts/).
Responsable: Daniel. Todos los valores se pueden cambiar en `LLMSettings` (el Admin los edita desde la colección
`settings`). Lo que **no** se puede cambiar desde ahí son las reglas de seguridad del §4.

## 1. Valores por defecto

| Parámetro (`LLMSettings`) | Valor | Rango permitido |
|---|---|---|
| `provider` | `anthropic` | `anthropic` (`openai` y `gemini` son stubs que fallan con un mensaje claro) |
| `generation_model` | `claude-sonnet-5-5` | cualquier id de modelo |
| `generation_effort` | `medium` | `low` · `medium` · `high` · `xhigh` · `max` |
| `generation_max_tokens` | 32 000 | 1 024 – 128 000 |
| `verification_model` | `claude-haiku-5-5` | cualquier id de modelo |
| `verification_effort` | `low` | igual que arriba |
| `verification_max_tokens` | 4 000 | 256 – 128 000 |
| `max_candidates` | 20 | 1 – 50 |
| `enable_fallbacks` | `true` | — |
| `timeout_seconds` | 600 | > 0 |
| `max_retries` | 2 | 0 – 10 |

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

## 3. Pendiente de verificar con el API real

Los tests usan `FakeLLMProvider` y un cliente SDK falso; no llaman a Claude. Falta comprobar con una llamada real:

1. Que el API acepta el esquema adaptado por `wire.py` (`anyOf`, `const`, `$ref`).
2. Que `fallbacks: "default"` se acepta junto con `output_config`. Si da 400, correr con `--no-fallbacks` y
   reportarlo a Daniel.

```bash
cd backend && uv run --no-project --python 3.12 --with 'pydantic>=2.9' --with httpx --with jsonpath-ng \
  --with pyyaml --with jinja2 --with anthropic python -m scripts.smoke_generate tests/fixtures/openapi_search.yaml -n 5
```

## 4. Reglas fijas (no configurables)

- La API key va en `backend/.env` (`ANTHROPIC_API_KEY`) y la lee el SDK; nunca se guarda en `settings` ni en Mongo.
- El texto del OpenAPI se sanea, se trunca y va delimitado en `<api_spec>`; los intentos de cerrar el delimitador se
  neutralizan.
- Las respuestas de la SUT nunca se envían al LLM.
- Toda salida del LLM se valida con Pydantic antes de usarse.
- Los tests y la CI nunca llaman al LLM real.

## 5. Para los experimentos

- Congelar `LLMSettings` y la versión del prompt antes del Hito M3 (mié 18) y no cambiarlos durante las corridas.
- Reportar en el paper modelo de generación, modelo de verificación, `effort`, `max_candidates`, versión del prompt y
  cuántas respuestas usaron fallback.
