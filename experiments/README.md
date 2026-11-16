# Experimentos

Evaluación de MetaREST en tres APIs: la **API demo** (`sut-demo`, con 8 fallos inyectables), **PokeAPI** y
**Crossref**. Todo lo que aparece en las tablas del paper sale de los CSV de [`results/`](results), generados con la
herramienta `mrexp` de esta carpeta.

## Contenido

| Ruta | Contenido | Versionado |
|---|---|---|
| [`config/experiment.json`](config/experiment.json) | Configuración **congelada** del pipeline para todos los runs | sí |
| [`specs/`](specs) | OpenAPI curados de PokeAPI y Crossref, y el de la API demo ([README](specs/README.md)) | sí |
| [`mrexp/`](mrexp) | Herramientas: runs, etiquetado, RQ1, RQ2, cobertura, mutantes (RQ3), cobertura de código y calibración | sí |
| [`manual_mrs/<api>/`](manual_mrs) | MRs manuales de la línea base: 8 de la demo, 7 de PokeAPI y 6 de Crossref | sí |
| [`results/`](results) | CSV para el paper, con nombres `<nombre>_<métrica>.csv` | sí |
| [`figures/`](figures) | `make_figures.py` y las figuras `fig_*.png`/`.pdf` | sí |
| [`sus/`](sus) | Protocolo SUS, plantilla de respuestas y `score.py` | sí |
| [`LABELING.md`](LABELING.md) | Guía para etiquetar la validez de las MRs (RQ1) | sí |
| `raw/` | Exportes de los runs y evidencia HTTP | no (`.gitignore`) |
| `cache/` | Caché local | no |

## Resultados

### Runs

Todos los runs usan [`config/experiment.json`](config/experiment.json):

- generación con `gemini-4-hydrogen` y verificación con `gemini-3.5-flash-lite`, ambos con esfuerzo `medium`;
- 20 MRs por run, con los prompts `gen_v1`, `semcheck_v2` y `faultcheck_v2`;
- umbrales `min_semantic` 0.6, `min_fault_revealing` 0.5 y similitud 0.975.

Los runs públicos son del commit `7bf7693` del pipeline. Ninguno tuvo errores ni chequeos LLM fallidos.

| Run | Generadas | Semántica | Potencial de fallo | Redundantes | Pasan el filtro | Ejecución | Tokens |
|---|---|---|---|---|---|---|---|
| `pokeapi_run1` | 20 | −1 | −2 | −1 | 16 | 16 pass | 95k |
| `pokeapi_run2` | 20 | 0 | −2 | 0 | 18 | 18 pass | 100k |
| `crossref_run1` | 20 | 0 | 0 | −3 | 17 | 15 pass, 1 violation, 1 error | 154k |
| `crossref_run2` | 20 | −1 | 0 | −6 | 13 | 13 pass | 151k |
| `demo_run1` | 20 | −1 | −1 | −6 | 12 | 12 pass | 83k |

- **Violación real** (`crossref_run1`): `GET /types` **ignora `rows` y `offset`** y siempre devuelve los 30 tipos,
  aunque su OpenAPI documenta esos parámetros.
- **Error** (`crossref_run1`): la MR agrega `filter=has-public-references:true` a `/members`, pero ese filtro solo
  existe en `/works` y la API responde 400. Es una MR inválida que el filtro dejó pasar.

### RQ1 · Validez antes y después del filtro

Se etiquetó el `run1` de cada API pública con dos etiquetadores; los desacuerdos se resolvieron en `label_final`.

| API | Acuerdo | Kappa | Válidas antes | Válidas después | Válidas descartadas | Inválidas descartadas |
|---|---|---|---|---|---|---|
| PokeAPI | 20/20 | indefinida (nadie marcó `0`) | 20/20 (100 %) | 16/16 (100 %) | 4 (1 semántica, 2 potencial de fallo, 1 redundante) | — |
| Crossref | 14/20 | 0.35 | 17/20 (85 %) | 14/17 (82 %) | 3 (redundantes) | 0 de 3 |

- El filtro **no subió** la proporción de válidas: en PokeAPI no había inválidas, y en Crossref las 3 inválidas
  pasaron.
- Los 6 desacuerdos de Crossref eran sobre si `sort=created` da un orden estable. Se resolvieron con la precondición
  de datos estables y desempate determinista.
- Las descartadas por potencial de fallo o por redundancia no son errores de validez: esas etapas miden otra cosa.

### RQ2 · Diversidad

- **Redundancia**: en la demo baja de 0.35 en las generadas a 0 tras el filtro (umbral 0.975). En
  `results/*_rq2.csv` también está con umbral 0.95.
- **Fallo único perdido**: la MR descartada como redundante «Añadir filtro de categoría no aumenta el total» era la
  única que detectaba `wrong_total`. El filtro la consideró duplicada de «Alargar la subcadena q no aumenta el total»
  (similitud 0.975, justo el umbral): misma relación `count_leq` sobre `$.total`, pero distinto parámetro
  transformado. La firma estructural da poco peso a qué parámetro se cambia.
- Con todas las candidatas (`demo_all`), MetaREST detecta 7/8. Una MR descartada por semántica también detecta
  `page_off_by_one`, pero ese fallo ya lo detecta una seleccionada.

### RQ3 · Detección de fallos (API demo)

MetaREST = las 12 que pasaron el filtro. El QA las aceptó todas, así que `--select accepted` da lo mismo.

| Técnica | Ítems | Fallos detectados | No detecta |
|---|---|---|---|
| tradicional | 11 | 8/8 | — |
| manual | 8 | 7/8 | `ignore_category` |
| MetaREST | 12 | 6/8 | `wrong_total`, `limit_dependent_order` |
| tradicional + MetaREST | 23 | 8/8 | — |
| manual + MetaREST | 20 | 8/8 | — |

- **Efecto techo**: la suite tradicional ya detecta los 8 fallos, así que ninguna combinación puede superarla. Lo
  informativo es manual + MetaREST: 8/8, cada una cubre el hueco de la otra.
- Ningún ítem falla en el original (`items_not_passing_original = 0`).
- Amenaza a la validez: la misma persona escribió los fallos y la suite tradicional.

### Cobertura

Operaciones y parámetros documentados que ejercitan las MRs. En PokeAPI y Crossref se suman los dos runs. En la
demo, `/health` cuenta como operación.

| API | MetaREST generadas | MetaREST seleccionadas | Manuales |
|---|---|---|---|
| demo | 2/3 · 6/6 | 1/3 · 5/6 | 1/3 · 5/6 |
| PokeAPI | 15/15 · 22/22 | 14/15 · 21/22 | 3/15 · 5/22 |
| Crossref | 12/18 · 46/92 | 11/18 · 43/92 | 5/18 · 9/92 |

Cobertura de código de la demo, medida con coverage.py con ramas sobre el original:

| Técnica | Ítems | Líneas | Ramas | Total |
|---|---|---|---|---|
| tradicional | 11 | 54/61 | 11/18 | 82 % |
| manual | 8 | 51/61 | 8/18 | 75 % |
| MetaREST | 12 | 51/61 | 8/18 | 75 % |
| todas | 31 | 54/61 | 11/18 | 82 % |

Casi todas las líneas sin cubrir son las de los fallos inyectados, que solo corren con `FAULTS`. Por eso el 100 % no
es alcanzable sobre el original.

### RQ4 · Esfuerzo de revisión

- **Revisión**: un revisor (autor del proyecto) aceptó las 12 MRs de la demo en 8.1 min. Mediana 3.6 s, media
  40.6 s, rango de 0.5 s a 3.7 min (`results/demo_review_times.csv`).
- **No representativo**: 6 decisiones tardaron menos de 1.2 s, que no alcanza para leer una MR, así que estos
  tiempos no estiman el esfuerzo de un auditor independiente.
- **SUS**: no se alcanzó a hacer. El protocolo está listo en [`sus/PROTOCOL.md`](sus/PROTOCOL.md).

## Cómo reproducirlo

Todos los comandos se corren desde `experiments/`, con las dependencias del backend (ver [`AGENTS.md`](../AGENTS.md)).
Algunos comandos necesitan paquetes adicionales:

| Comandos | Paquetes adicionales |
|---|---|
| `run`, `rq2` | `--with fastembed` |
| `mutants` | `--with fastapi --with uvicorn --with pytest` |
| `code-coverage` | los de `mutants` y además `--with coverage` |

`run` llama al LLM real, con la key en `backend/.env`. Las métricas no llaman a ningún LLM.

### 1. Runs de MetaREST

```bash
python -m mrexp run pokeapi --name pokeapi_run1
python -m mrexp run crossref --name crossref_run1
python -m mrexp run demo --name demo_run1 --spec specs/demo.json --base-url http://127.0.0.1:8150
```

- **Salida**: cada run escribe `raw/<name>.json` con todas las candidatas, incluidas las descartadas, y un bloque
  `meta` con el commit, el sha256 del spec y de la config, y los límites del cliente HTTP.
- **Sin sobrescribir**: nunca sobrescribe un run existente; para hacerlo hay que pasar `--force`.
- **Runs fallidos**: si el run termina con error o falla algún chequeo LLM, se guarda como `raw/<name>.failed.json`
  y no sirve para RQ1.
- **Copia de seguridad**: guarda también los runs fuera del repo, porque las tablas salen de ellos.

### 2. Etiquetado y RQ1

1. Crea la hoja de etiquetado:
   ```bash
   python -m mrexp label-sheet raw/pokeapi_run1.json --name pokeapi
   ```
2. Etiqueta siguiendo [`LABELING.md`](LABELING.md):
   - el etiquetador A llena `results/<api>_labels.csv` y el B su copia `results/<api>_labels_b.csv`;
   - ninguno ve la hoja del otro;
   - la hoja es ciega (sin decisión del filtro, scores ni veredicto) y viene barajada con semilla fija.
3. Junta las dos hojas, resuelve los desacuerdos en `label_final` y calcula RQ1:
   ```bash
   python -m mrexp merge-labels results/pokeapi_labels.csv results/pokeapi_labels_b.csv
   python -m mrexp rq1 raw/pokeapi_run1.json --labels results/pokeapi_labels.csv --name pokeapi
   ```

### 3. RQ3: mutantes de la API demo

El runner levanta la API demo una vez por fallo, en los puertos `--port`, `--port`+1, etc.

```bash
F=filter_or,wrong_total,repeat_page,drop_on_sort,ignore_limit,page_off_by_one,ignore_category,limit_dependent_order
python -m mrexp mutants --name demo --run raw/demo_run1.json --select passed --manual manual_mrs/demo \
  --tests ../sut-demo/tests --serve "python -m uvicorn app:create_app --factory --app-dir ../sut-demo --port {port}" \
  --faults $F
python -m mrexp mutants --name demo_all --run raw/demo_run1.json --select all ...   # mismas opciones
```

Con servidores ya levantados se puede usar `--variant original=http://localhost:8001 --variant ignore_limit=...` en
lugar de `--serve`.

### 4. RQ2 y cobertura

```bash
python -m mrexp rq2 raw/demo_run1.json --threshold 0.95 --threshold 0.975 \
  --detections results/demo_all_detections.csv --name demo
python -m mrexp coverage specs/pokeapi.yaml raw/pokeapi_run1.json --manual manual_mrs/pokeapi --name pokeapi
python -m mrexp code-coverage --name demo --run raw/demo_run1.json --manual manual_mrs/demo --tests ../sut-demo/tests \
  --serve "uvicorn app:create_app --factory --app-dir ../sut-demo --port {port}" --source ../sut-demo/app.py
```

`code-coverage` detiene el servidor con SIGTERM. En Windows no se guardan datos.

### 5. Revisión del QA en la plataforma

Las MRs de un run se revisan en la UI sin regenerarlas. Desde la raíz del repo, con el stack de Docker Compose
levantado ([`infra/README.md`](../infra/README.md)):

1. En la UI, crea el proyecto «API demo» con `experiments/specs/demo.json` y la URL base `http://sut-demo:8001`.
2. Importa el run:
   ```bash
   docker compose --env-file backend/.env -f infra/docker-compose.yml exec -T backend \
     python -m scripts.import_run --project "API demo" < experiments/raw/demo_run1.json
   ```
3. Revisa las candidatas como QA. La UI mide el tiempo de revisión.
4. Exporta el run con las decisiones:
   ```bash
   docker compose --env-file backend/.env -f infra/docker-compose.yml exec -T backend \
     python -m scripts.export_run demo_run1 > experiments/raw/demo_run1_reviewed.json
   ```
5. Corre RQ3 solo con las aceptadas: `mutants --name demo_accepted --run raw/demo_run1_reviewed.json --select accepted`,
   con las mismas opciones que en el paso 3. Los tiempos de revisión salen de `GET /audit?run_id=demo_run1`.

### 6. Figuras, SUS y calibración

```bash
uv run --no-project --python 3.12 --with matplotlib python figures/make_figures.py
python sus/score.py sus/responses.csv
python -m mrexp calibrate --name calib \
  --case pokeapi=raw/smoke_pokeapi_gemini.json --case crossref=raw/smoke_crossref_gemini.json \
  --config gemini-3.5-flash-lite:low:v1 --config gemini-3.5-flash-lite:medium:v2
```

La calibración llama al LLM real y usa los smoke runs, nunca los de RQ1. `--config` tiene la forma
`modelo:esfuerzo:versión de prompt`. Los resultados y la decisión están en [`docs/LLM.md`](../docs/LLM.md) (D15).

## Definiciones

- **MR válida**: la relación debe cumplirse en cualquier implementación correcta de la API y la MR se puede ejecutar
  tal como está. Las no ejecutables vienen con `0` prellenado en la hoja.
- **RQ1**: proporción de válidas antes (todas) y después (las que pasan) del filtro, por etiquetador y acordada.
  También se reportan el kappa de Cohen, la matriz de confusión del filtro y las válidas perdidas en cada etapa. Una
  candidata con desacuerdo sin resolver no entra en las tasas.
- **RQ2**: los clusters son las componentes conexas del grafo «coseno ≥ umbral», sobre la misma firma estructural que
  usa el filtro. Con el umbral del run, las que pasan tienen redundancia 0 por construcción.
- **RQ3**: un ítem (MR o test) **detecta** un fallo si pasa en el original y no pasa en la variante con ese fallo.
  Por defecto también cuenta un `error` (por ejemplo un 500); con `--strict` solo cuentan `violation` y `fail`.
  Salidas:
  - `*_detections.csv`: ítem × variante;
  - `*_rq3_summary.csv`: resultado de cada combinación de técnicas;
  - `*_rq3_fault_matrix.csv`: fallo × técnica.
- **Cobertura**: operaciones y pares (operación, parámetro) documentados que ejercitan las peticiones concretas de las
  MRs, contando todas sus instancias.

## Tests

```bash
python -m pytest -q
```

Usan un catálogo falso en `tests/fixtures/demo_sut.py`, que solo depende de la stdlib y no es la API demo real, y una
suite tradicional de ejemplo. El test de punta a punta levanta un servidor por variante. Nunca llaman al LLM real.
