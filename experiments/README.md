# Experimentos

| Carpeta | Contenido | Versionado |
|---|---|---|
| `specs/` | OpenAPI curados de PokeAPI y Crossref ([README](specs/README.md)) y el de la API demo (`demo.json`) | sí |
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
3. ~~RQ3, cobertura con manuales, cobertura de código~~: hechos el 16-nov (ver la última sección).

## MRs manuales, RQ3 en la demo, figuras y SUS (16-nov-2026)

- `manual_mrs/{demo,pokeapi,crossref}/`: 8 + 7 + 6 MRs de la línea base, escritas desde los contratos de cada API. Las 21
  pasan contra la API original (demo local, PokeAPI y Crossref reales).
- RQ3 en la demo (`results/demo_manual_*.csv`, suite tradicional + manuales, sin MRs de MetaREST todavía):

| Combinación | Ítems | Fallos detectados |
|---|---|---|
| tradicional | 11 | 8/8 |
| manual | 8 | 7/8 (no detecta `ignore_category`) |
| tradicional + manual | 19 | 8/8 |

  Falta correr `run demo` (LLM real) y repetir `mutants` con `--run raw/demo_run1.json --select accepted`.
- Figuras: `uv run --no-project --python 3.12 --with matplotlib python figures/make_figures.py` → `figures/fig_*.png|pdf`.
- SUS: [`sus/PROTOCOL.md`](sus/PROTOCOL.md), plantilla `sus/responses.csv` y `sus/score.py`.

## API demo: run, RQ3, RQ2 y cobertura (16-nov-2026)

Spec: `specs/demo.json` (el `/openapi.json` que sirve `sut-demo` sin fallos). Run `demo_run1` con la configuración
congelada: 20 generadas → −1 semántica, −1 potencial de fallo, −6 redundantes → **12 pasan** el filtro, las 12 `pass`
en el original (83k tokens). Comandos:

```bash
python -m mrexp run demo --name demo_run1 --spec specs/demo.json --base-url http://127.0.0.1:8150
F=filter_or,wrong_total,repeat_page,drop_on_sort,ignore_limit,page_off_by_one,ignore_category,limit_dependent_order
python -m mrexp mutants --name demo --run raw/demo_run1.json --select passed --manual manual_mrs/demo \
  --tests ../sut-demo/tests --serve "python -m uvicorn app:create_app --factory --app-dir ../sut-demo --port {port}" --faults $F
python -m mrexp mutants --name demo_all --run raw/demo_run1.json --select all ...   # mismas opciones
python -m mrexp rq2 raw/demo_run1.json --threshold 0.95 --threshold 0.975 --detections results/demo_all_detections.csv --name demo
python -m mrexp code-coverage --name demo --run raw/demo_run1.json --manual manual_mrs/demo --tests ../sut-demo/tests \
  --serve "uvicorn app:create_app --factory --app-dir ../sut-demo --port {port}" --source ../sut-demo/app.py
```

(`mutants` y `code-coverage` necesitan además `--with fastapi --with uvicorn --with pytest`, y `code-coverage`
`--with coverage`; `code-coverage` usa SIGTERM, así que no guarda datos en Windows.)

**RQ3** (`results/demo_rq3_*.csv`; MetaREST = las 12 que pasan el filtro, todavía sin revisión del QA):

| Técnica | Ítems | Fallos detectados | No detecta |
|---|---|---|---|
| tradicional | 11 | 8/8 | — |
| manual | 8 | 7/8 | `ignore_category` |
| MetaREST | 12 | 6/8 | `wrong_total`, `limit_dependent_order` |
| tradicional + MetaREST | 23 | 8/8 | — |
| manual + MetaREST | 20 | 8/8 | — |

- **Efecto techo**: la suite tradicional ya detecta los 8 fallos, así que en esta demo ninguna combinación puede
  superarla. La comparación útil es por técnica y manual + MetaREST (8/8, cada una cubre el hueco de la otra).
  Amenaza a la validez: los fallos y la suite tradicional los escribió la misma persona.
- Ninguna MR ni test falla en el original (`items_not_passing_original = 0`).

**RQ2** (`results/demo_rq2*.csv`): redundancia de las generadas 0.35 → 0 tras el filtro (umbral 0.975). Pero **una MR
descartada por redundante detecta un fallo que ninguna seleccionada detecta**: «Añadir filtro de categoría no
aumenta el total» (detecta `wrong_total`) se consideró duplicada de «Alargar la subcadena q no aumenta el total»
(similitud 0.975, justo el umbral): misma relación `count_leq` sobre `$.total`, distinto parámetro transformado.
La firma estructural de D12 pesa poco qué parámetro se cambia. Con todas las candidatas (`demo_all`), MetaREST
detecta 7/8. Una MR descartada por semántica también detecta `page_off_by_one`.

**Cobertura de la API** (`results/{demo,pokeapi,crossref}_coverage.csv`, operaciones / parámetros documentados):

| API | MetaREST generadas | MetaREST seleccionadas | Manuales |
|---|---|---|---|
| demo | 2/3 · 6/6 | 1/3 · 5/6 | 1/3 · 5/6 |
| PokeAPI | 15/15 · 22/22 | 14/15 · 21/22 | 3/15 · 5/22 |
| Crossref | 12/18 · 46/92 | 11/18 · 43/92 | 5/18 · 9/92 |

(En la demo `/health` cuenta como operación.)

**Cobertura de código de la demo** (`results/demo_code_coverage.csv`, coverage.py con ramas, en el original):

| Técnica | Ítems | Líneas | Ramas | Total |
|---|---|---|---|---|
| tradicional | 11 | 54/61 | 11/18 | 82 % |
| manual | 8 | 51/61 | 8/18 | 75 % |
| MetaREST | 12 | 51/61 | 8/18 | 75 % |
| todas | 31 | 54/61 | 11/18 | 82 % |

Las líneas no cubiertas son sobre todo las de los fallos inyectados (solo corren con `FAULTS`), así que el máximo
alcanzable en el original es menor que 100 %.
