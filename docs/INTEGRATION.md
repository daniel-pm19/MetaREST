# Integración del pipeline (backend, API demo, líneas base)

Qué necesita cada parte del equipo del pipeline de MRs (`backend/app/pipeline/`, Daniel) y qué necesitan los
experimentos (`experiments/`) de las demás partes. Contrato del MR: [`MR_SCHEMA.md`](MR_SCHEMA.md). Modelos, umbrales
y decisiones del LLM: [`LLM.md`](LLM.md). Comandos de los experimentos: [`experiments/README.md`](../experiments/README.md).

## 1. Backend (Nestor)

### 1.1 Punto de entrada

Todo el pipeline es una sola función async. No lanza excepciones por fallos esperados (spec inválido, LLM caído,
cuota agotada): los deja en `report.error` y marca las etapas restantes como `skipped`.

```python
from app.pipeline.orchestrator import PipelineSettings, RunReport, run_pipeline
from app.pipeline.llm import create_provider
from app.pipeline.embeddings import FastEmbedEmbedder
from app.pipeline.executor import SUTClient

EMBEDDER = FastEmbedEmbedder("BAAI/bge-small-en-v1.5", cache_dir="/data/fastembed")  # uno por proceso


async def execute_run(project, run_doc, settings: PipelineSettings, prompts: dict) -> None:
    async def save_progress(report: RunReport) -> None:  # se llama al empezar y terminar cada etapa
        await runs.update_one({"_id": run_doc.id}, {"$set": {"report": report.model_dump(mode="json")}})

    async with SUTClient(
        project.base_url,
        headers=project_headers(project),  # credenciales de la SUT leídas de .env (auth_env_key), nunca de Mongo
        max_concurrency=project.max_concurrency,
        min_interval=project.min_interval,
        timeout=project.timeout,
    ) as sut:
        result = await run_pipeline(
            project.openapi,  # texto/bytes/dict del OpenAPI 3.x o Swagger 2.0 que subió el usuario
            project_id=str(project.id),
            run_id=str(run_doc.id),
            provider=create_provider(settings.llm),
            embedder=EMBEDDER,
            sut=sut,  # None = no ejecutar (las candidatas quedan sin `execution`)
            settings=settings,
            prompts=prompts,  # {prompt_id: PromptTemplate} editados por el Admin; {} = los del repo
            on_progress=save_progress,
        )
    await candidates.insert_many([{"_id": c.id, **c.model_dump(mode="json")} for c in result.candidates])
    await runs.update_one(
        {"_id": run_doc.id},
        {"$set": {
            "status": "awaiting_review" if result.report.ok else "failed",
            "report": result.report.model_dump(mode="json"),
            "counts": result.counts,  # {"pending_review": 7, "discarded": 3, "redundant": 2, ...}
        }},
    )
```

- Lánzalo con `BackgroundTasks` (o `asyncio.create_task`) y responde `202` con el id del run; el frontend hace
  polling de `GET /runs/{id}` y pinta `report.stages[]` (`name`, `status`, `input_count`, `output_count`,
  `duration_ms`, `usage`, `detail`). Un run de 20 MRs con Gemini tarda unos 2–4 min (generación ~40 s +
  chequeos limitados a 12 peticiones/min + ejecución).
- `EMBEDDER` carga el modelo (~70 MB) la primera vez que se usa. En Docker, monta `cache_dir` en un volumen o
  descárgalo al construir la imagen para que el primer run no espere la descarga.
- Las API keys del LLM se leen del entorno: `GEMINI_API_KEY` o `ANTHROPIC_API_KEY` (en `.env`). Sin key, el run
  termina con `report.error = "Gemini: falta GEMINI_API_KEY..."`.
- Las respuestas de la SUT nunca van al LLM, y el ejecutor solo hace GET/HEAD. No hace falta nada extra del
  backend para cumplir esas dos reglas.

### 1.2 Settings (Admin)

`PipelineSettings` es Pydantic: guárdalo con `model_dump(mode="json")` y valida con `model_validate` lo que mande el
Admin (así los rangos inválidos dan 422 sin escribir validaciones a mano).

| Campo | Qué es |
|---|---|
| `llm` (`LLMSettings`) | proveedor, modelos, esfuerzo, `max_candidates`, `requests_per_minute`… |
| `filters` (`FilterSettings`) | pesos, umbrales (`min_semantic`, `min_fault_revealing`, `similarity_threshold`), prompts de chequeo |
| `generation_prompt` | id del prompt de generación (`gen_v1`) |
| `execution_concurrency` | MRs ejecutadas en paralelo |

- **Guarda una copia completa en cada run** (`run.settings`): es lo que se reporta en el paper y lo que lee el export.
- `LLMSettings` rellena modelos, esfuerzo de verificación y límite de peticiones según el proveedor **solo para los
  campos que no se envían**. Si el Admin cambia de proveedor, valida `{"provider": "anthropic"}` sin arrastrar los
  modelos del proveedor anterior (si no, quedaría Anthropic con modelos de Gemini).
- Prompts editables: `PromptTemplate.from_strings(prompt_id, system, user)`. Los ids que usa el pipeline salen de
  los settings (`generation_prompt`, `filters.semantic_prompt`, `filters.fault_prompt`); los del repo se listan con
  `app.pipeline.prompts.available_prompts()`. Una versión editada debe tener un id nuevo (p. ej. `gen_v1_admin1`)
  para que la trazabilidad del run diga cuál se usó.

### 1.3 Candidatas y decisiones

- Cada `MRCandidate` se guarda tal cual (`_id = c.id`). Su esquema está en
  [`schemas/mr_candidate.schema.json`](schemas/mr_candidate.schema.json) y hay ejemplos en
  [`mr_examples/candidates/`](mr_examples/candidates/).
- `POST /candidates/{id}/decision` solo acepta candidatas en `pending_review` y las pasa a `accepted` o `rejected`
  (justificación obligatoria al rechazar). Las `discarded` son finales. La decisión se **agrega** a `decisions`
  (append-only) con usuario, fecha, decisión, justificación, `provenance` del candidato y **tiempo de revisión**
  (`review_time_ms`, lo mide el frontend): RQ4 sale de ahí.
- El backend no vuelve a validar el MR ni toca `scores`/`filter_result`/`execution`.

### 1.4 Export para los experimentos (`GET /candidates/export?run_id=...`)

`experiments/mrexp` lee exactamente este formato (el mismo que escribe `backend/scripts/smoke_pipeline.py`):

```json
{
  "settings":   { "...": "run.settings (PipelineSettings)" },
  "report":     { "...": "run.report (RunReport)" },
  "candidates": [ { "...": "MRCandidate con el status actual (accepted / rejected / pending_review / discarded)" } ]
}
```

- **Todas** las candidatas del run, también las descartadas (RQ1 y RQ2 las necesitan).
- `status` actualizado con las decisiones del QA: `mrexp mutants --select accepted` ejecuta solo las aceptadas.
- Opcional en CSV para humanos; los experimentos usan el JSON.

## 2. API demo `sut-demo/` (Nestor) — requisitos para RQ3

El runner (`python -m mrexp mutants ... --serve`) levanta la API una vez por variante y necesita:

| Requisito | Por qué |
|---|---|
| Fallos activables con la variable `FAULTS` (lista separada por comas; vacía = sin fallos) | una variante por fallo |
| Puerto por línea de comandos (`uvicorn app.main:app --port {port}`) | levanta varias variantes |
| `GET /health` responde 200 cuando está lista | el runner espera a que arranque |
| Datos **deterministas** (catálogo fijo, sin aleatoriedad ni dependencia de la hora) | una MR o test solo detecta un fallo si pasa en el original |
| Cada fallo observable con GET (p. ej. `ignore_limit`, `wrong_total`, `page_off_by_one`, `sort_unstable`, `filter_or_instead_of_and`, `drops_last_page_item`…) | el ejecutor solo hace GET/HEAD |
| OpenAPI en `/openapi.json` con descripciones, `example`s, `enum`s y rangos | es lo que lee el generador |
| Nombres de fallo estables (son las columnas de las tablas del paper) | |

- Los ejemplos de [`MR_SCHEMA.md` §8](MR_SCHEMA.md#8-supuesto-de-los-ejemplos-api-demo) asumen `GET /search` con
  `q`, `limit`, `page`, `sort` y `category`. Si la API demo termina con otra forma, avísame y actualizo los ejemplos.
- **Cobertura de código** con coverage.py: sirve el mismo comando con
  `--serve "coverage run --parallel-mode -m uvicorn app.main:app --port {port}"` y `[run] sigterm = true` en la
  config de coverage (el runner detiene el servidor con SIGTERM).

### Suite tradicional (Nestor)

Una suite pytest en `sut-demo/tests/` (y una por API pública si da tiempo) que lea la URL de la variable
`SUT_BASE_URL`. El runner la corre contra cada variante (`--tests ../sut-demo/tests`) y lee el JUnit XML: un test
detecta un fallo si pasa en el original y falla en la variante.

## 3. MRs manuales (Isaac) — línea base de RQ3

- Un archivo por MR en `experiments/manual_mrs/<api>/` (`demo`, `pokeapi`, `crossref`), con un `MRSpec` (o una
  lista). Mismo esquema que genera el LLM: [`MR_SCHEMA.md`](MR_SCHEMA.md) y
  [`schemas/mr_spec.schema.json`](schemas/mr_spec.schema.json); hay ejemplos en
  [`mr_examples/specs/`](mr_examples/specs/). El nombre del archivo es el id de la MR en las tablas.
- Se escriben **sin mirar** las MRs generadas por MetaREST (si no, la línea base no es independiente).
- Para comprobar que todas son válidas y pasan en la API sin fallos:

  ```bash
  cd experiments
  python -m mrexp mutants --name manual_check --manual manual_mrs/pokeapi --variant original=https://pokeapi.co
  ```

  Un MR inválido detiene el comando con el error de validación; en `results/manual_check_detections.csv` cada MR
  debería tener `pass` en `original`.

## 4. Frontend (Isaac)

- Tipos desde `/openapi.json` (`npm run gen:types`). Mientras el backend no exista, los JSON de
  `docs/mr_examples/candidates/` sirven de mocks.
- Revisión de una candidata: `spec.title`, `spec.description`, `spec.expected_relation`, `spec.rationale`; la
  petición fuente y los follow-ups (`spec.source`, `spec.followups[].transformations`); `scores.semantic_validity`
  y `scores.fault_revealing` (`score`, `llm_reason`, `rule_violations`) y `scores.combined`; el veredicto
  (`execution.verdict`: `pass`, `violation`, `error`) con la evidencia de `execution.instances[]`.
- Descartadas: `filter_result.reason` (`not_executable`, `invalid_semantics`, `low_fault_revealing`, `redundant`),
  `filter_result.detail` y, si es redundante, `filter_result.duplicate_of`. Para `not_executable` no hay `spec`:
  mostrar `raw_output`.
- Progreso del run: `report.stages[]` (ver §1.1); tokens por run en `report.stages[].usage`.
