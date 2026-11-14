# Experimentos

| Carpeta | Contenido | Versionado |
|---|---|---|
| `specs/` | OpenAPI curados de PokeAPI y Crossref ([README](specs/README.md)) | sí |
| `config/experiment.json` | Configuración **congelada** del pipeline para todos los runs de experimento | sí |
| `mrexp/` | Herramientas: runs, hoja de etiquetado, RQ1, RQ2, cobertura, runner de mutantes (RQ3) y calibración | sí |
| `manual_mrs/<api>/` | MRs manuales de la línea base (Isaac), un `.json` por MR con el esquema `MRSpec` | sí |
| `results/` | CSVs para el paper (`<nombre>_<métrica>.csv`) | sí |
| `raw/` | Exportes de runs y evidencia HTTP del runner | no (`.gitignore`) |
| `cache/` | Caché local | no |

Proveedor LLM de los experimentos: **Gemini** (`docs/LLM.md`, D14).

## Configuración congelada

`config/experiment.json` es un `PipelineSettings` completo (todos los campos escritos, así un cambio de los valores
por defecto del código no altera los experimentos): generación `gemini-4-hydrogen` (esfuerzo `medium`), verificación
`gemini-3.5-flash-lite` (esfuerzo `medium`, D15), 20 MRs por run, prompts `gen_v1` / `semcheck_v2` /
`faultcheck_v2`, umbrales `min_semantic` 0.6, `min_fault_revealing` 0.5, similitud 0.975. **No se edita** durante los
experimentos; si hubiera que cambiarlo, se repiten todos los runs.

## Entradas

- **Exporte de un run**: JSON `{"meta", "settings", "report", "candidates"}` (`meta` es opcional) con **todas** las candidatas, incluidas las
  descartadas. Lo escriben `backend/scripts/smoke_pipeline.py --out ...` y, cuando exista, el export del backend
  (`GET /candidates/export`). También se acepta una lista de candidatas sola.
- **MRs manuales**: `manual_mrs/<api>/*.json`, cada archivo con un `MRSpec` (o una lista). Mismo esquema que el
  pipeline (`docs/MR_SCHEMA.md`), así se ejecutan con el mismo ejecutor. Una MR manual inválida detiene el runner.
- **Tests tradicionales** (Nestor): una suite pytest que lee la URL de la SUT de `SUT_BASE_URL`.
- **API demo** (Nestor): el runner necesita que acepte `FAULTS=<fallo>` (vacío = sin fallos), el puerto por
  línea de comandos y que responda `GET /health`.

## Comandos

Desde `experiments/`, con las dependencias del backend (ver `AGENTS.md`; `run` y `rq2` además `--with fastembed`).

Runs de MetaREST con la configuración congelada (llaman al LLM real; la key va en `backend/.env`):

```bash
python -m mrexp run pokeapi --name pokeapi_run1
python -m mrexp run crossref --name crossref_run1
python -m mrexp run demo --name demo_run1 --spec ../sut-demo/openapi.json --base-url http://localhost:8001
```

Escribe `raw/<name>.json` con todas las candidatas y un bloque `meta` (commit, sha256 del spec y de la config,
límites del cliente HTTP). Nunca sobrescribe un run existente (`--force` para hacerlo). Si el run terminó con error o
algún chequeo LLM falló (se habría puntuado solo con reglas, D11), lo guarda como `raw/<name>.failed.json` y hay que
repetirlo: ese run no sirve para RQ1. Los runs de experimento quedan en `raw/` (no versionado); guárdalos también fuera
del repo, porque las tablas del paper salen de ellos.

Métricas:

```bash
python -m mrexp label-sheet raw/pokeapi_run1.json --name pokeapi
python -m mrexp merge-labels results/pokeapi_labels.csv results/pokeapi_labels_b.csv
python -m mrexp rq1 raw/pokeapi_run1.json --labels results/pokeapi_labels.csv --name pokeapi
python -m mrexp rq2 raw/pokeapi_run1.json --threshold 0.95 --threshold 0.975 --name pokeapi
python -m mrexp coverage specs/pokeapi.yaml raw/pokeapi_run1.json --manual manual_mrs/pokeapi --name pokeapi
```

RQ3, levantando la API demo una vez por fallo (puerto `--port`, `--port+1`, …):

```bash
python -m mrexp mutants --name demo \
  --run raw/demo_run1.json --select accepted --manual manual_mrs/demo --tests ../sut-demo/tests \
  --serve "uvicorn app.main:app --port {port}" --serve-cwd ../sut-demo \
  --faults ignore_limit,wrong_total,page_off_by_one
```

O con servidores ya levantados: `--variant original=http://localhost:8001 --variant ignore_limit=http://localhost:8002 ...`.

Calibración de la verificación (llama al LLM real; usa los smoke runs, nunca los de RQ1):

```bash
python -m mrexp calibrate --name calib \
  --case pokeapi=raw/smoke_pokeapi_gemini.json --case crossref=raw/smoke_crossref_gemini.json \
  --config gemini-3.5-flash-lite:low:v1 --config gemini-3.5-flash-lite:medium:v2
```

`--config` es `modelo:esfuerzo:versión de prompt`. Resultados y decisión en `docs/LLM.md` (D15).

## Métricas y decisiones

- **Hoja de etiquetado (RQ1)**: incluye todas las candidatas, **a ciegas** (sin decisión del filtro, scores ni
  veredicto, porque solo se ejecutan las que pasan) y barajadas con semilla fija. Cada etiquetador llena su
  columna (`label_a` / `label_b`: `1` válida, `0` inválida) sin ver la otra; los desacuerdos se resuelven después
  en `label_final`. Las no ejecutables vienen con `0` prellenado (se puede cambiar). Válida = la relación debe
  cumplirse en una implementación correcta de la API y la MR se puede ejecutar como está.
- **RQ1**: proporción válida antes (todas) y después (las que pasan) del filtro, por etiquetador y acordada;
  kappa de Cohen; matriz de confusión del filtro (precisión, recall de válidas, inválidas eliminadas) y, por
  etapa de descarte, cuántas válidas se perdieron. Una candidata con desacuerdo sin resolver no entra en las tasas.
- **RQ2**: clusters = componentes conexas del grafo «coseno ≥ umbral» sobre la misma firma estructural que usa el
  filtro. Se reporta para las generadas, las que llegaron a diversidad y las que pasaron. Con el umbral del run,
  las que pasaron tienen redundancia 0 por construcción; se pueden pedir otros umbrales con `--threshold`.
  Con `--detections results/demo_all_detections.csv` (de `mutants --select all --name demo_all`) dice si alguna
  MR descartada por redundante detectaba un fallo que ninguna seleccionada detecta.
- **RQ3**: un ítem (MR o test) **detecta** un fallo si pasa en `original` y no pasa en la variante con ese fallo.
  Exigir `pass` en el original descarta MRs incorrectas y tests inestables, y trata igual a MRs y tests. Por
  defecto también cuenta un `error` (p. ej. un 500); `--strict` cuenta solo `violation` / `fail`. Salidas:
  `*_detections.csv` (ítem × variante), `*_rq3_summary.csv` (cada combinación: tradicional, +manual, +MetaREST…)
  y `*_rq3_fault_matrix.csv` (fallo × técnica).
- **Cobertura**: operaciones y pares (operación, parámetro) documentados que ejercitan las peticiones concretas de
  las MRs (todas las instancias). La cobertura de código de la API demo se mide aparte con coverage.py.

## Tests

`python -m pytest -q` (ver `AGENTS.md`). Usan un catálogo falso en `tests/fixtures/demo_sut.py` (solo stdlib, no es
la API demo real) y una suite tradicional de ejemplo; el test de punta a punta levanta un servidor por variante.

## Estado (13-nov-2026)

Runs de experimento hechos con `config/experiment.json` (commit `7bf7693` del pipeline), los 4 utilizables
(sin errores ni chequeos LLM fallidos):

| Run | Generadas | Semántica | Potencial de fallo | Redundantes | Pasan el filtro | Ejecución | Tokens |
|---|---|---|---|---|---|---|---|
| `pokeapi_run1` | 20 | −1 | −2 | −1 | 16 | 16 pass | 95k |
| `pokeapi_run2` | 20 | 0 | −2 | 0 | 18 | 18 pass | 100k |
| `crossref_run1` | 20 | 0 | 0 | −3 | 17 | 15 pass, 1 violation, 1 error | 154k |
| `crossref_run2` | 20 | −1 | 0 | −6 | 13 | 13 pass | 151k |

- `crossref_run1`, violación: `GET /types` **ignora `rows` y `offset`** (siempre devuelve los 30 tipos) aunque el
  OpenAPI los documenta. Es una discrepancia real entre spec e implementación, buen ejemplo para el paper.
- `crossref_run1`, error: la MR agrega `filter=has-public-references:true` a `/members`, filtro que solo existe en
  `/works` (400). MR inválida que el filtro no detectó; queda para RQ1.
- Salidas: `results/{pokeapi,crossref}_labels.csv` (hojas de RQ1, solo `run1`: 20 MRs cada una, para que el
  etiquetado quepa en el tiempo), `*_rq2*.csv` y `*_coverage*.csv` (los dos runs).

RQ1 (`run1` de cada API, 2 etiquetadores, desacuerdos resueltos en `label_final`):

| API | Acuerdo | Kappa | Válidas antes del filtro | Válidas después | Válidas descartadas | Inválidas descartadas |
|---|---|---|---|---|---|---|
| PokeAPI | 20/20 | 1.00 (degenerada: nadie usó `0`) | 20/20 (100 %) | 16/16 (100 %) | 4 (1 semántica, 2 potencial de fallo, 1 redundante) | — |
| Crossref | 14/20 | 0.35 | 17/20 (85 %) | 14/17 (82 %) | 3 (redundantes) | 0 de 3 |

- El filtro **no subió** la proporción de válidas: en PokeAPI no había inválidas, y en Crossref las 3 inválidas pasaron.
  Los 6 desacuerdos de Crossref eran todos sobre si `sort=created` da un orden estable (la guía lo afirmaba al
  principio y se corrigió a zona gris); se resolvieron con la etiqueta de A.
- Las descartadas por potencial de fallo o redundancia no son errores de validez (miden otra cosa).

Pendiente:
1. ~~Etiquetar~~ (hecho para `run1`). Para repetirlo, seguir [`LABELING.md`](LABELING.md): A en `results/<api>_labels.csv`, B en su copia
   `results/<api>_labels_b.csv`, sin ver la del otro. Después `merge-labels`, resolver desacuerdos en `label_final`
   y correr `rq1` por API: `python -m mrexp rq1 raw/pokeapi_run1.json --labels results/pokeapi_labels.csv --name pokeapi`.
2. Revisar las MRs en la UI (o marcar `status` aceptadas) para `--select accepted`.
3. RQ3 cuando existan `sut-demo`, su suite tradicional y las MRs manuales: `run demo` y luego `mutants`
   (y `mutants --select all --name demo_all` + `rq2 --detections` para la pregunta de redundantes).
4. Cobertura con las MRs manuales (`coverage ... --manual manual_mrs/<api>`).
