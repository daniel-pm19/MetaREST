# API demo de Nestor

Datos fijos (96 elementos), OpenAPI en `/openapi.json`, salud en `/health`.
Desde la raíz del repositorio:

```powershell
cd backend
uv run uvicorn app:create_app --factory --app-dir ../sut-demo --host 127.0.0.1 --port 8001
```

Antes de iniciar, configura `FAULTS` con una lista de nombres separados por comas.
Vacía significa original sano. Los nombres no reconocidos impiden arrancar.
Hay ocho fallos: `filter_or`, `wrong_total`, `repeat_page`, `drop_on_sort`,
`ignore_limit`, `page_off_by_one`, `ignore_category`, `limit_dependent_order`.

El contrato es `GET /search?q=&category=&limit=&page=&sort=` y responde
`{total,results:[{id,name,category,price}]}`. `q` es substring sin distinguir
mayúsculas, categoría se combina con AND, `total` se mide antes de paginar.
Orden por ID o precio, límites 1–100 y páginas desde 1. Los términos fijos son
jazz, rock, blues y guitar; cada uno tiene 24 resultados, 12 vinyl y 12 cd.
La API no expone endpoints para modificar datos o activar fallos desde una petición.

Pruebas tradicionales contra una instancia ya iniciada:

```powershell
$env:SUT_BASE_URL = "http://127.0.0.1:8001"
uv run pytest ../sut-demo/tests -q
```

O comprobación automática del original y todas las variantes (servidores reales,
reporte JSON, sin LLM), desde `backend`:

```powershell
uv run python -m scripts.check_demo_baseline
```

Para RQ3 usa el runner de Daniel desde `experiments`, con su entorno de dependencias
activo (por ejemplo `../backend/.venv/Scripts/python.exe` en Windows):

```text
python -m mrexp mutants --tests ../sut-demo/tests --serve "python -m uvicorn app:create_app --factory --app-dir ../sut-demo --port {port}" --faults filter_or,wrong_total,repeat_page,drop_on_sort,ignore_limit,page_off_by_one,ignore_category,limit_dependent_order --name demo_baseline
```

`--manual` y `--run` se agregan cuando existan las MRs manuales independientes y
las salidas del LLM sobre esta API. La suite no usa relaciones entre ejecuciones:
comprueba entradas fijas, valores esperados, esquema, filtros, paginación y límites.
No se debe debilitar para favorecer a MetaREST. Puede detectar todos los fallos
de esta demo, lo cual no establece que una técnica sea mejor para otras APIs.

Una MR de subconjunto no detecta por sí sola un parámetro ignorado: la igualdad
también cumple subconjunto. `count_leq` tampoco detecta siempre un filtro ignorado.
Se conserva esta limitación en las pruebas de integración del pipeline.
