# Checklist de avance — MVP MetaREST

Estado frente a [`PLAN.md`](PLAN.md), por persona. Verificado contra el contenido de `develop` (commit `c45a501`) el **15-nov-2026 (Día 4)**.
Lo que alguien tenga solo en local y no haya subido a `develop` figura como pendiente.

Leyenda: `[x]` hecho · `[~]` parcial · `[ ]` pendiente

> Actualización de Nestor (15-nov-2026): las marcas de su bloque incluyen trabajo local sobre `0904ff6`, todavía sin commit/push. Los hitos publicados y los estados de Daniel/Isaac conservan su evaluación anterior.


## Resumen

| Persona | Área | Estado | Avance |
|---|---|---|---|
| **Daniel** | Pipeline IA + runner de experimentos | Casi completo | ██████████░ ~90 % |
| **Nestor** | Plataforma backend, sut-demo, infra | Backend y demo implementados localmente; infraestructura preparada, sin desplegar | Ver bloque detallado |
| **Isaac** | Frontend, MRs manuales, SUS | Frontend completo y alineado con el backend; falta prueba end-to-end y la parte de experimentos | ███████░░░░ ~75 % |

| Hito | Fecha | Estado |
|---|---|---|
| D0 Contrato MR congelado | mié 11-nov | [x] Hecho (`models/mr.py`, `MR_SCHEMA.md`) |
| M1 Flujo completo con `docker compose up` | sáb 14-nov | [ ] **No cumplido**: no existe API HTTP, base de datos ni docker |
| M2 Feature freeze + app desplegada con 3 roles | lun 16-nov | [ ] **En riesgo**: depende de todo el backend de Nestor |
| M3 CSVs y figuras de experimentos | mié 18-nov | [~] Parcial: solo PokeAPI y Crossref (RQ1, RQ2, cobertura) |
| Entrega | vie 20-nov | [ ] Pendiente |

> **Cuello de botella:** sin API HTTP (Nestor) el frontend no puede conectarse al backend real, el export para los experimentos no existe y no se puede desplegar. Es la ruta crítica.

---

## Daniel — Pipeline IA y experimentos

### Hecho
- [x] Contrato MR ejecutable (`backend/app/models/mr.py`) y `docs/MR_SCHEMA.md` con ejemplos y JSON Schemas
- [x] Capa LLM: `LLMProvider`, Anthropic, Gemini, `FakeLLMProvider`, límite de peticiones, manejo de errores de API key
- [x] Extractor de contexto OpenAPI 3.x y Swagger 2.0
- [x] Prompts versionados (`gen_v1`, `semcheck_v1/v2`, `faultcheck_v1/v2`) y generador con salida estructurada
- [x] Filtros: validez semántica, potencial de fallos, diversidad (embeddings locales con fastembed) y scorer ponderado
- [x] Ejecutor: solo GET/HEAD, transformaciones, relaciones, selectores JSONPath y caché
- [x] Orquestador con progreso por etapa y tokens (`run_pipeline`)
- [x] Tests del pipeline con LLM falso
- [x] Documentación: `LLM.md`, `INTEGRATION.md`, `SUTS.md`, `LABELING.md`, `experiments/README.md`
- [x] Selección de SUTs públicas: PokeAPI y Crossref, con specs curados
- [x] Calibración de umbrales y modelos
- [x] Herramientas de experimentos `mrexp`: runs, hoja de etiquetado, RQ1, RQ2, cobertura, runner de mutantes (RQ3)
- [x] Resultados RQ1, RQ2 y cobertura para PokeAPI y Crossref (`experiments/results/`)

### Pendiente
- [ ] Run, etiquetado, RQ1, RQ2 y cobertura sobre la **API demo** (necesita `sut-demo/` de Nestor)
- [ ] **RQ3**: ejecutar el runner de mutantes sobre la API demo (necesita `sut-demo/` y la suite tradicional de Nestor, y las MRs manuales de Isaac)
- [ ] Cobertura de código con coverage.py en la API demo
- [ ] Análisis RQ4 (tiempos de revisión) a partir del log de decisiones, cuando exista backend
- [ ] Revisar los umbrales con los primeros runs de la API demo
- [ ] Secciones 7 (Resultados), 8 (Conclusión) y 9 (Trabajo futuro) del paper, con el equipo

---

## Nestor — Plataforma backend, API demo e infraestructura

> Actualización local del 15-nov-2026, basada en `0904ff6`: backend, autenticación, endpoints y API demo implementados y probados. Cambios todavía sin publicar. La infraestructura tiene recetas preparadas; su despliegue no se considera hecho.

Verificación: 267 pruebas backend, 31 de experimentos, 25 pruebas de plataforma
repetidas contra MongoDB 7 real, build frontend correcto y manifiestos Compose
válidos. Suite tradicional: 11 casos en el original; detecta los 8 fallos de la
demo. Docker Desktop no proporcionó un motor disponible en este equipo.

### Backend base
- [x] Scaffold FastAPI con `uv` y `backend/pyproject.toml` (requisitos en `AGENTS.md`)
- [x] `GET /health`
- [x] Configuración con pydantic-settings y `.env`
- [x] Modelos Beanie/MongoDB: `users`, `projects`, `api_contexts`, `prompt_templates`, `settings`, `runs`, `candidates`, `decisions` (append-only), `audit_log`
- [x] **`docs/API.md`**: contrato de endpoints que el frontend necesita ya

### Autenticación y permisos
- [x] Login con JWT + bcrypt, `GET /auth/me`
- [x] `require_role()` con Admin, QA Auditor y Observer
- [x] Seed del usuario admin
- [x] CRUD de `/users` (Admin)

### Endpoints
- [x] `POST /projects` (con subida del OpenAPI), `PUT/GET /projects`
- [x] `POST /projects/{id}/runs` (202 + `BackgroundTasks`, usando `execute_run` de `INTEGRATION.md §1.1`)
- [x] `GET /runs/{id}` (con `report.stages[]`, `counts`, `status`) y listado de runs por proyecto
- [x] `GET /runs/{id}/candidates?status=`
- [x] `POST /candidates/{id}/decision` (justificación obligatoria al rechazar, solo `pending_review`, guarda `review_time_ms`)
- [x] `GET /audit` y filtro por `run_id`
- [x] `GET /metrics/project/{id}` y `GET /metrics/compare?runs=`
- [x] `GET/PUT /settings/llm`, `/settings/thresholds`, versiones de `/prompts` (ediciones crean un id nuevo para preservar provenance)
- [x] **`GET /candidates/export?run_id=`** (JSON y CSV; lo necesitan los experimentos)
- [x] Tests de RBAC por endpoint

### API demo (`sut-demo/`) — bloquea RQ1–RQ3 sobre la demo
- [x] Catálogo con `GET /search` (`q`, `limit`, `page`, `sort`, `category`), datos deterministas
- [x] 8 fallos activables con `FAULTS=` (`ignore_limit`, `wrong_total`, `page_off_by_one`, `filter_or`, `repeat_page`, `drop_on_sort`, `ignore_category`, `limit_dependent_order`), todos observables con GET
- [x] Puerto por línea de comandos y `GET /health`
- [x] `/openapi.json` con descripciones, ejemplos, enums y rangos
- [x] Suite pytest tradicional (`SUT_BASE_URL`) para la demo (11 casos; original y 8 variantes comprobados). Las suites públicas opcionales siguen pendientes

### Infraestructura y despliegue
- [x] `infra/docker-compose.yml`: build y arranque completo comprobados el 16-nov-2026; frontend en 8082, proxy, login, red backend→demo y persistencia de Mongo tras recrear contenedores
- [~] `ci.yml` preparado: ruff, pytest con Mongo real en CI, experimentos y build frontend; pendiente ejecutarlo en GitHub
- [ ] Instancia EC2 t3.medium, security group y subdominio DuckDNS
- [~] `docker-compose.prod.yml` y Nginx HTTPS preparados; manifiesto validado; faltan dominio, certificado y despliegue real
- [~] `deploy.yml` preparado: CI exitoso en main → GHCR → SSH verificado a EC2; sin ejecutar
- [~] Script mongodump→S3 y regla de retención de 7 días preparados; falta configurar bucket, cron, restauración y CloudWatch
- [x] Volumen fastembed verificado en Docker: descarga y embedding de 384 dimensiones; tras recrear contenedores carga offline desde la caché persistente

---

## Isaac — Frontend, MRs manuales, SUS y figuras

### Hecho (`frontend/`, subido a `develop`)
- [x] Scaffold Vite + React 18 + TypeScript + Tailwind, layout con sidebar y navegación móvil
- [x] Tipos generados desde el JSON Schema del backend (`npm run gen:types`)
- [x] Cliente de API con modo demostración (mock con la forma exacta de `MRCandidate`) y modo backend real (`VITE_API_URL`)
- [x] **Resumen**: métricas, progreso del pipeline por etapa con tokens, polling mientras corre
- [x] **Revisión de candidatas**: lista con búsqueda y filtros, detalle con scores, razón del LLM, transformaciones, evidencia de ejecución y veredicto
- [x] Aceptar/rechazar con justificación obligatoria al rechazar y medición de `review_time_ms`
- [x] **Descartadas por el filtro** con motivo, detalle y `duplicate_of`
- [x] **Decisiones / trazabilidad**
- [x] Accesibilidad básica: foco visible, roles ARIA, `prefers-reduced-motion`
- [x] **Login y roles** (Admin, Auditor QA, Observador): sesión con JWT, menú y acciones según rol, rutas protegidas, expiración de sesión
- [x] **Proyectos**: listar, abrir y registrar una API subiendo su OpenAPI (JSON/YAML, validado en el cliente)
- [x] **Comparar iteraciones** (2 a 4) con cambios entre ellas
- [x] **Métricas en el resumen**: fallos confirmados y tasa de aceptación, tokens por iteración
- [x] **Administración**: usuarios y roles, modelo LLM, umbrales del filtro y versiones de prompts
- [x] Selector de proyecto y selector de iteración (por defecto la más reciente)
- [x] Tipos de Run/Etapas derivados de `/openapi.json` (`src/api/schema.ts`, `npm run gen:api`); `run.ts` ya no los escribe a mano
- [x] ESLint (`npm run lint`) con reglas de hooks; TypeScript fijado en 6 porque typescript-eslint no soporta TS 7

### Pendiente — frontend
- [x] Costo estimado por run en el Resumen: precios por modelo vía `VITE_LLM_PRICES` (el repo no trae precios); cota inferior, sin tokens de caché
- [x] **Conectado al backend real** (16-nov): probado en el navegador con `VITE_API_URL` contra el backend de Nestor (Mongo simulado con mongomock, LLM falso, API demo real como SUT): login por rol, registro de proyecto con OpenAPI, run completo, revisión con evidencia, aceptar/rechazar, decisiones, descartadas, comparar, selector de iteración, usuarios, umbrales, LLM y prompts. Se corrigieron tres desajustes (proyecto inexistente con base vacía, `requests_per_minute` vacío, contraseña 12–72). Falta repetirlo contra Mongo real y Docker. Los mocks se conservan para el modo demostración
- [~] `gen:api` usa `openapi.snapshot.json` (o `OPENAPI_URL`); regenerar el snapshot si cambia el backend. `Decision` sigue a mano porque `/audit` no tiene `response_model`
- [x] Prettier aplicado a `src/` (`npm run format`) y 19 pruebas con Vitest + Testing Library (`npm test`): cliente demo y permisos por rol, costo, componentes, Login y axe
- [~] Accesibilidad: prueba automática con axe-core sobre Login (sin contraste ni layout, que jsdom no calcula). Faltan la revisión manual en móvil y con lector de pantalla

> Los endpoints que el frontend asume y que Nestor debe confirmar: `POST /auth/login` (`{email, password}` → `{access_token, user}`), `GET /auth/me`, `GET /projects/{id}/runs`, `GET /metrics/compare?runs=`, `GET/POST/PATCH /users`, `GET/PUT /settings/llm` y `/settings/thresholds`, `GET/POST /prompts`. Ver `frontend/src/api/client.ts`.
>
> Matiz sobre roles: el plan solo deja decidir y lanzar iteraciones al QA; por indicación de Isaac, el Admin también puede (control total) y el Observador solo lee. El backend debe aplicar la misma regla.

> Desviación del plan: no se usó shadcn/ui, React Router ni TanStack Query/MSW; se usan Tailwind, rutas por hash y un mock propio. Se puede migrar si el equipo lo prefiere.

### Pendiente — experimentos y paper
- [x] **MRs manuales**: 8 (demo), 7 (PokeAPI) y 6 (Crossref) en `experiments/manual_mrs/`, escritas desde el OpenAPI y el README de la demo sin mirar MRs generadas; las 21 pasan en la API original. Salvedad: ya conocía los nombres de los fallos inyectados de la demo
- [x] Etiquetado de validez (RQ1) como segundo etiquetador (`label_b`) en PokeAPI y Crossref; acuerdo, kappa y resolución en `experiments/README.md`. Pendiente solo si se quiere etiquetar también el run de la demo
- [~] **SUS**: protocolo, tareas, cuestionario en español, plantilla de respuestas y script de puntuación en `experiments/sus/`. `responses.csv` solo tiene el encabezado: faltan las sesiones con ≥ 5 personas reales (no se pueden simular) y reportar n, media, mediana y rango
- [x] Figuras del paper: `experiments/figures/make_figures.py` genera RQ1, RQ2, cobertura y RQ3 (PNG y PDF)

---

## Riesgos activos

| Riesgo | Impacto | Acción propuesta |
|---|---|---|
| Backend de plataforma sin publicar | Bloquea frontend real, despliegue, export y RQ3 | Nestor sube lo que tenga a `develop` hoy y publica `docs/API.md` |
| `sut-demo/` inexistente | Sin RQ3 ni resultados sobre la API demo | Priorizar una primera versión con 3–4 fallos para desbloquear a Daniel |
| Feature freeze el lun 16 | Poco margen para integrar | Acordar el contrato de endpoints hoy; el frontend ya espera los de `PLAN.md §1.4` |
| Sin participantes para el SUS | RQ4 incompleto | Isaac agenda sesiones esta semana |
