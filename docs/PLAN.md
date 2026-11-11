# Plan de acción — MVP MetaREST (11-nov → vie 20-nov-2026)

## Contexto

El artículo propone **MetaREST**: una herramienta que (1) extrae contexto de una especificación OpenAPI, (2) genera con un LLM relaciones metamórficas (MRs) candidatas para una API REST, (3) las filtra por **validez semántica, potencial de revelar fallos y diversidad funcional**, (4) ejecuta las supervivientes contra la API bajo prueba (SUT) y (5) se las presenta a un QA Auditor que acepta o rechaza (con justificación obligatoria), dejando un log de auditoría. El repo `MetaREST` está vacío (solo LICENSE/README, rama `develop`). Hay que construir el MVP completo, desplegarlo y correr los experimentos (RQ1–RQ4) para llenar las secciones 7–9 del paper, en **10 días calendario** con **3 personas (Daniel, Nestor, Isaac), cada una con Claude/Codex**.

### Decisiones ya tomadas (confirmadas con el equipo)
| Tema | Decisión |
|---|---|
| Entrega | Vie 20-nov, se trabaja el fin de semana |
| LLM | Abstracción multi-proveedor; implementación inicial **Anthropic Claude**. Embeddings **locales** |
| Despliegue | **AWS EC2 + Docker Compose + Nginx/HTTPS + GitHub Actions CI/CD** (cuenta AWS sí, **sin dominio** → DuckDNS + Let's Encrypt) |
| Auth | **JWT + bcrypt + 3 roles** (Admin, QA Auditor, Observer) en API y UI |
| SUTs | **3 APIs**: 1 API demo propia con fallos inyectables + 2 APIs públicas |
| Experimentos | Dentro del alcance: RQ1–RQ4, cobertura, SUS. Líneas base (tests tradicionales + MRs manuales) **escritas por el equipo** |
| UI | Diseño libre, en español (las figuras del paper solo como referencia de vistas) |
| Formato del plan | Este documento se versiona como `docs/PLAN.md` en el repo |

---

## 1. Arquitectura del MVP

Monolito modular (como el paper). Monorepo:

```
MetaREST/
├── AGENTS.md / CLAUDE.md        # convenciones compartidas para Claude/Codex (ver §6)
├── docs/PLAN.md, docs/API.md, docs/MR_SCHEMA.md
├── backend/                     # Python 3.12, FastAPI, Pydantic v2, uv
│   ├── app/main.py, config.py (pydantic-settings, .env)
│   ├── app/auth/                # bcrypt, JWT (python-jose/pyjwt), dependencias require_role()
│   ├── app/db/                  # Motor + Beanie (ODM sobre MongoDB)
│   ├── app/models/              # Documentos Beanie + esquemas Pydantic (fuente de verdad)
│   ├── app/api/routers/         # auth, users, projects, runs(pipeline), candidates, approve, audit, metrics, settings, health
│   ├── app/pipeline/
│   │   ├── context_extractor.py # parse OpenAPI 3.x (+ conversión Swagger 2) → ApiContext compacto
│   │   ├── prompts/             # plantillas Jinja2 versionadas (gen_v1, semcheck_v1, faultcheck_v1)
│   │   ├── llm/                 # LLMProvider (Protocol) + AnthropicProvider; stubs OpenAI/Gemini; factory por config
│   │   ├── generator.py         # zero-shot, salida estructurada (tool use) → list[MRCandidate]
│   │   ├── filters/             # semantic.py, fault_revealing.py, diversity.py, scorer.py
│   │   ├── embeddings.py        # fastembed (ONNX, bge-small) — ligero para la t3.medium
│   │   ├── executor/            # httpx async, solo GET/HEAD, caché de respuestas, transformaciones y comparadores
│   │   └── orchestrator.py      # corre las etapas, actualiza estado del run, registra tokens/tiempos
│   └── tests/                   # pytest + mongomock/testcontainers, LLM falso para tests
├── frontend/                    # Vite + React 18 + TypeScript, React Router, TanStack Query, Tailwind + shadcn/ui, Recharts
│   └── src/api/types.ts         # generado con openapi-typescript desde /openapi.json del backend
├── sut-demo/                    # API demo FastAPI (catálogo/búsqueda) con fallos activables por env/flag
├── experiments/                 # baselines (pytest tradicional, MRs manuales), runner de mutantes, scripts de métricas, notebooks/figuras
├── infra/
│   ├── docker-compose.yml       # dev: mongo, backend, frontend(vite), sut-demo
│   ├── docker-compose.prod.yml  # prod: nginx(+React build), backend, mongo (volumen), sut-demo
│   ├── nginx/                   # /api → backend, estáticos, HTTPS
│   └── scripts/                 # backup mongodump → S3, bootstrap EC2
└── .github/workflows/           # ci.yml (lint+tests+build), deploy.yml (push a main → GHCR → SSH a EC2)
```

### 1.1 Decisión clave: MR ejecutable (contrato que se congela el Día 0)

El paper define `source_endpoint`, `target_endpoint`, `transformation_logic`, `expected_relation`. Para poder **ejecutarlas** de forma determinista, el LLM no devuelve texto libre sino un objeto estructurado validado por Pydantic:

```jsonc
{
  "id": "...", "run_id": "...", "description": "Reducir limit debe devolver un subconjunto",
  "source":   { "method": "GET", "path": "/items", "params": {"q": "jazz", "limit": 20} },
  "followup": { "method": "GET", "path": "/items",          // = target_endpoint
                "transformations": [ {"op": "set_param", "param": "limit", "value": 10} ] },
  "relation": { "type": "subset",                           // catálogo cerrado (abajo)
                "source_selector": "$.results[*].id", "followup_selector": "$.results[*].id",
                "direction": "followup_in_source" },
  "transformation_logic": "texto legible", "expected_relation": "texto legible",
  "rationale": "...", "provenance": {"model": "...", "prompt_version": "gen_v1"},
  "scores": {...}, "filter": {...}, "execution": {...}, "status": "pending|accepted|rejected|discarded"
}
```

- **Transformaciones** (catálogo cerrado): `set_param`, `remove_param`, `add_param`, `scale_param`, `append_to_param`, `swap_path_param`.
- **Relaciones** (patrones de Segura et al. + 2 útiles): `equivalence`, `equality`, `subset`, `disjoint`, `complete`, `difference`, `count_leq`, `same_order`. Selectores con JSONPath (`jsonpath-ng`).
- Valores de entrada: el LLM propone 1–3 instancias de entrada por MR; si faltan se usan `example`s del OpenAPI.
- Lo que no encaje en el catálogo → descartado con razón `not_executable` (cuenta para RQ1).

### 1.2 Pipeline (POST /runs)

1. **Extracción de contexto**: endpoints GET/HEAD, parámetros (tipo, enum, min/max, ejemplos), esquema de respuesta resumido. Descripciones del OpenAPI tratadas como datos no confiables (delimitadas en el prompt).
2. **Generación** (`claude-sonnet-5-5`, configurable): N candidatas (tope configurable, p. ej. 30) vía tool use con el JSON Schema del MR. Registro de tokens.
3. **Filtro** (orden y descarte con razón):
   - *Validez semántica*: reglas Python (endpoint/params existen, tipos/enums válidos, método seguro, selector compatible con el esquema de respuesta, relación compatible con el tipo — p. ej. `subset` exige array) + chequeo LLM (`claude-haiku-5-5`) → score 0–1 + razón.
   - *Potencial de revelar fallos*: reglas (la transformación cambia algo, la relación no es tautológica, source ≠ followup) + chequeo LLM → score 0–1.
   - *Diversidad*: embeddings locales del texto canónico de la MR; selección greedy por score combinado descartando las de coseno ≥ umbral con una ya seleccionada (se guarda `duplicate_of`).
   - Score combinado ponderado; **umbrales y pesos editables por Admin**.
4. **Ejecución** de las supervivientes contra la SUT (solo GET/HEAD, timeout, caché de respuestas, credenciales del SUT solo desde `.env`) → `pass | violation | error` con evidencia (requests, status, extracto de respuestas). Las respuestas **no** se envían al LLM.
5. Run queda en `awaiting_review`. Ejecución en **BackgroundTasks + polling** (`GET /runs/{id}`) para mostrar el progreso por etapa (evita timeouts tras Nginx).

### 1.3 Colecciones MongoDB

`users`, `projects` (nombre, base_url, spec OpenAPI, `auth_env_key` opcional), `api_contexts`, `prompt_templates` (versionadas), `settings` (LLM, umbrales), `runs` (snapshot de config, modelo, versión de prompt, estado/etapas, tiempos, tokens), `candidates` (MR + scores + decisión del filtro + ejecución), `decisions` (**append-only**: usuario, fecha, decisión, justificación, modelo, prompt, tiempo de revisión), `audit_log`.

### 1.4 API REST (FastAPI) y permisos

| Endpoint | Admin | QA | Observer |
|---|---|---|---|
| `POST /auth/login`, `GET /auth/me` | ✔ | ✔ | ✔ |
| `CRUD /users` | ✔ | | |
| `GET/PUT /settings/llm`, `/settings/thresholds`, `CRUD /prompts` | ✔ | | |
| `POST /projects` (+ upload OpenAPI), `PUT /projects/{id}` | ✔ | ✔ | |
| `GET /projects`, `GET /projects/{id}` | ✔ | ✔ | ✔ |
| `POST /projects/{id}/runs` (= `POST /pipeline` del paper) | | ✔ | |
| `GET /runs/{id}`, `GET /runs/{id}/candidates?status=` (= `GET /results`) | ✔ | ✔ | ✔ |
| `POST /candidates/{id}/decision` (= `POST /approve`; rechazo exige justificación) | | ✔ | |
| `GET /audit`, `GET /metrics/project/{id}`, `GET /metrics/compare?runs=` | ✔ | ✔ | ✔ |
| `GET /candidates/export` (JSON/CSV para experimentos) | ✔ | ✔ | |
| `GET /health` | público |

### 1.5 Vistas del frontend (español)

Login · Proyectos (registrar API + subir OpenAPI) · **Ejecutar iteración** (lanzar + progreso por etapa) · **Revisión de candidatos** (lista + detalle: scores, evidencia de ejecución, aceptar/rechazar con justificación; mide tiempo de revisión) · **Descartados por el filtro** (con razón) · **Comparar iteraciones** · **Dashboard** (tasa de aceptación, violaciones confirmadas, tokens/costo por run) · **Trazabilidad** (log inmutable) · Admin (usuarios, LLM, prompts, umbrales). La UI oculta lo que el rol no permite.

---

## 2. Responsables (propuesta, ajustable en el kickoff)

| Persona | Área principal | Área secundaria |
|---|---|---|
| **Daniel** | Pipeline IA: contrato MR, capa LLM, prompts, generador, filtros, diversidad, ejecutor, orquestador | Runner de mutantes y métricas RQ1–RQ3 |
| **Nestor** | Plataforma backend: esqueleto FastAPI, Mongo/Beanie, auth JWT/RBAC, routers, auditoría, métricas; **API demo con fallos**; infra (Docker, CI/CD, EC2, Nginx, HTTPS, backups, CloudWatch) | Suite de tests tradicionales (baseline) |
| **Isaac** | Frontend completo (todas las vistas, roles en UI, tipos generados, mocks) | MRs manuales (baseline), sesiones SUS, figuras del paper |

Ruta crítica: **contrato MR (D0) → generador+filtros+ejecutor (Daniel) → integración con runs/candidates (Nestor) → revisión en UI (Isaac) → experimentos**.

---

## 3. Cronograma día a día

### Día 0 — mié 11-nov · Kickoff y contratos (todos)
- Validar este plan y la asignación. Crear `AGENTS.md`/`CLAUDE.md` (§6).
- **Daniel**: `backend/app/models/mr.py` (MR, transformaciones, relaciones) + `docs/MR_SCHEMA.md` con 3 ejemplos. **Congelado al final del día.**
- **Nestor**: scaffold monorepo, `uv`, FastAPI `/health`, `docker-compose.yml` dev (mongo+backend+frontend), `ci.yml` (ruff, pytest, build frontend). Crear instancia EC2 t3.medium + security group + subdominio DuckDNS.
- **Isaac**: scaffold Vite+React+TS+Tailwind+shadcn, layout/sidebar, router, cliente API, MSW con mocks basados en el contrato MR.
- Ramas: `main` (protegida, despliega), `develop` (integración), `feat/<area>-<tema>`; PR a `develop` con 1 revisión + CI verde.

### Días 1–3 — jue 12 a sáb 14 · Construcción en paralelo
- **Daniel**: `LLMProvider` + `AnthropicProvider` (tool use, conteo de tokens, reintentos) y stubs OpenAI/Gemini; `context_extractor`; prompt `gen_v1` + `generator`; reglas semánticas y de fault-revealing + chequeos LLM; diversidad con fastembed; `scorer`; `executor` (transformaciones, JSONPath, 8 comparadores, caché); `orchestrator`. Tests con LLM falso.
- **Nestor**: modelos Beanie de todas las colecciones; auth (bcrypt, JWT con expiración, `require_role`), seed de admin; routers projects/runs/candidates/decision/audit; **sut-demo** (catálogo con búsqueda, filtros, paginación, orden, total; ~8–10 fallos activables por variable `FAULTS=ignore_limit,wrong_total,...`); `docker-compose.prod.yml` + Nginx; primer despliegue manual en EC2.
- **Isaac**: Login + guard por rol; Proyectos (registro + upload OpenAPI); Ejecutar iteración (lanzar + polling de etapas); esqueleto de Revisión de candidatos con mocks.
- **Hito M1 (sáb 14, noche)**: con `docker compose up`, un QA crea un proyecto con el OpenAPI de la API demo, lanza un run y ve candidatas filtradas y ejecutadas (aún sin pulir UI). Merge `develop → main`.

### Días 4–5 — dom 15 a lun 16 · Cierre funcional y despliegue
- **Daniel**: afinar prompts/umbrales con la API demo y las 2 públicas; export JSON/CSV; script `experiments/run_mutants.py` (corre MRs aceptadas contra cada fallo de la API demo).
- **Nestor**: métricas (`/metrics`, comparar runs), settings de Admin (LLM, umbrales, prompts), CRUD usuarios; `deploy.yml` (build → GHCR → SSH a EC2 → `compose pull && up -d`); HTTPS con certbot sobre DuckDNS; backup diario `mongodump`→S3 (retención 7 días); CloudWatch básico. **Suite pytest tradicional** para las 3 APIs (status, esquema, casos de borde).
- **Isaac**: Revisión completa (aceptar/rechazar con justificación, evidencia, tiempo de revisión), Descartados, Comparar iteraciones, Dashboard, Trazabilidad, Admin; quitar mocks y usar tipos generados. **MRs manuales** (~5–8 por API, en `experiments/manual_mrs/` con el mismo esquema JSON para reutilizar el ejecutor).
- **Selección de las 2 APIs públicas** (D4 a más tardar, responsable Daniel): criterios = OpenAPI disponible, endpoints GET con búsqueda/filtros/paginación, sin auth o con key gratuita, rate limit tolerable. Candidatas a evaluar: PokeAPI, JSONPlaceholder, REST Countries, Open Library — **decisión a confirmar con el equipo**.
- **Hito M2 (lun 16, noche) = feature freeze**: app pública en `https://<sub>.duckdns.org`, despliegue automático al hacer push a `main`, los 3 roles funcionando.

### Días 6–7 — mar 17 a mié 18 · Experimentos (solo bugfix en código)
- Para cada API: 1–2 runs de MetaREST; guardar todas las candidatas (incluidas descartadas).
- **RQ1**: etiquetado manual de validez de *todas* las candidatas (antes y después del filtro) por 2 personas; proporción válida pre/post filtro (+ acuerdo entre etiquetadores).
- **RQ2**: redundancia pre/post diversidad (clusters por similitud) y verificar si alguna descartada por diversidad detectaba fallos que ninguna seleccionada detecta.
- **RQ3** (solo API demo, por los fallos inyectados): fallos detectados por (a) tests tradicionales, (b) tradicionales + MRs manuales, (c) tradicionales + MetaREST. Cobertura: operaciones/parámetros ejercitados en las 3 APIs + cobertura de código (coverage.py) en la API demo.
- **RQ4**: tiempo por MR aceptada (del log de decisiones) y **SUS** (10 ítems) con ≥5 participantes (compañeros de QA/clase) — Isaac agenda las sesiones desde el D4.
- **Hito M3 (mié 18)**: CSVs y figuras en `experiments/results/`.

### Día 8 — jue 19 · Análisis y paper
- Secciones 7 (Resultados), 8 (Conclusión), 9 (Trabajo futuro). Ensayo de demo end-to-end en el entorno desplegado. Congelar `main` (tag `v1.0.0`).

### Día 9 — vie 20 · Entrega
- Buffer para correcciones, demo final.

---

## 4. Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| El LLM genera MRs no ejecutables o alucinadas | Salida estructurada + catálogo cerrado + validación Pydantic; descartar con razón |
| Costo/latencia del LLM | Tope de candidatas por run, Haiku para verificación, caché de respuestas del SUT, tokens visibles en dashboard |
| t3.medium (4 GB) sin memoria | fastembed (ONNX) en vez de torch; Mongo con `wiredTigerCacheSizeGB` bajo |
| Rate limits de APIs públicas | Caché de respuestas por request, pocas instancias por MR |
| Integración tardía frontend/backend | Contrato MR congelado D0, tipos generados de `/openapi.json`, MSW mientras tanto, merge a `develop` diario |
| Falta de tiempo para experimentos | Feature freeze estricto el lun 16; RQ3 solo en API demo |
| Sin participantes SUS | Agendar desde el D4; mínimo 5 |

---

## 5. Definición de "terminado" del MVP

- Un QA Auditor, desde el navegador en HTTPS, registra una API y su OpenAPI, lanza el pipeline, ve el progreso, revisa candidatas con scores y evidencia, acepta/rechaza con justificación y consulta descartadas, trazabilidad y métricas.
- Admin configura modelo LLM, prompts y umbrales; Observer solo lee. Permisos verificados en backend (no solo ocultos en UI).
- Push a `main` → tests → imágenes en GHCR → despliegue automático en EC2. Backup diario a S3.
- Resultados de RQ1–RQ4 y comparación de cobertura en `experiments/results/` y en el paper.

---

## 6. Trabajo con asistentes IA (Claude/Codex)

- `AGENTS.md` (y `CLAUDE.md` que lo referencia) en la raíz con: estructura del repo, comandos (`uv run pytest`, `npm run dev`, `docker compose up`), convenciones (ruff/black, ESLint/Prettier, nombres de ramas, commits convencionales), regla de **no modificar `models/mr.py` ni `docs/API.md` sin PR revisado por Daniel/Nestor**, y "solo GET/HEAD contra SUTs".
- Cada persona trabaja en su carpeta para evitar conflictos; cambios de contrato solo por PR.
- Daily de 15 min (estado vs. hito, bloqueos).

---

## 7. Verificación

- **Unitarias**: `uv run pytest` en backend (extractor con OpenAPIs de muestra, cada regla del filtro, cada comparador del ejecutor, diversidad con vectores fijos, RBAC por endpoint) usando un `FakeLLMProvider`.
- **Integración**: test que levanta `sut-demo` con un fallo activo (p. ej. `ignore_limit`) y comprueba que una MR `subset` sobre `limit` termina en `violation`, y sin fallos en `pass`.
- **E2E manual** en cada hito: flujo completo con los 3 roles en local (M1) y en la URL desplegada (M2).
- **CI**: lint + tests + build en cada PR; deploy verificado con `GET /health` tras el despliegue.

---

## 8. Primer paso tras aprobar este plan

Copiar este documento a `docs/PLAN.md` en `develop`, crear `AGENTS.md`/`CLAUDE.md`, y arrancar el Día 0 (scaffold + contrato MR).
