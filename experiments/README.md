# Experimentos

| Carpeta | Contenido | Versionado |
|---|---|---|
| `specs/` | OpenAPI curados de PokeAPI y Crossref ([README](specs/README.md)) | sí |
| `mrexp/` | Herramientas: hoja de etiquetado, RQ1, RQ2, cobertura y runner de mutantes (RQ3) | sí |
| `manual_mrs/<api>/` | MRs manuales de la línea base (Isaac), un `.json` por MR con el esquema `MRSpec` | sí |
| `results/` | CSVs para el paper (`<nombre>_<métrica>.csv`) | sí |
| `raw/` | Exportes de runs y evidencia HTTP del runner | no (`.gitignore`) |
| `cache/` | Caché local | no |

Proveedor LLM de los experimentos: **Gemini** (`docs/LLM.md`, D14).

## Entradas

- **Exporte de un run**: JSON `{"settings", "report", "candidates"}` con **todas** las candidatas, incluidas las
  descartadas. Lo escriben `backend/scripts/smoke_pipeline.py --out ...` y, cuando exista, el export del backend
  (`GET /candidates/export`). También se acepta una lista de candidatas sola.
- **MRs manuales**: `manual_mrs/<api>/*.json`, cada archivo con un `MRSpec` (o una lista). Mismo esquema que el
  pipeline (`docs/MR_SCHEMA.md`), así se ejecutan con el mismo ejecutor. Una MR manual inválida detiene el runner.
- **Tests tradicionales** (Nestor): una suite pytest que lee la URL de la SUT de `SUT_BASE_URL`.
- **API demo** (Nestor): el runner necesita que acepte `FAULTS=<fallo>` (vacío = sin fallos), el puerto por
  línea de comandos y que responda `GET /health`.

## Comandos

Desde `experiments/`, con las dependencias del backend (ver `AGENTS.md`; `rq2` además `--with fastembed`):

```bash
python -m mrexp label-sheet raw/pokeapi_run1.json --name pokeapi
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
