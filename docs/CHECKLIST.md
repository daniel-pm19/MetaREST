# Checklist de avance — MVP MetaREST

Estado frente a [`PLAN.md`](PLAN.md), por persona. Verificado contra el contenido de `develop` (commit `c45a501`) el **15-nov-2026 (Día 4)**.
Lo que alguien tenga solo en local y no haya subido a `develop` figura como pendiente.

Leyenda: `[x]` hecho · `[~]` parcial · `[ ]` pendiente

## Resumen

| Persona | Área | Estado | Avance |
|---|---|---|---|
| **Daniel** | Pipeline IA + runner de experimentos | Casi completo | ██████████░ ~90 % |
| **Nestor** | Plataforma backend, sut-demo, infra | **Sin entregas en el repo** | ░░░░░░░░░░░ 0 % |
| **Isaac** | Frontend, MRs manuales, SUS | Frontend completo con datos de demostración; falta conectarlo y la parte de experimentos | ███████░░░░ ~70 % |

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

> En `develop` no hay nada de esta área todavía (no existen `backend/app/main.py`, `pyproject.toml`, `sut-demo/`, `infra/` ni `.github/`).

### Backend base
- [ ] Scaffold FastAPI con `uv` y `backend/pyproject.toml` (requisitos en `AGENTS.md`)
- [ ] `GET /health`
- [ ] Configuración con pydantic-settings y `.env`
- [ ] Modelos Beanie/MongoDB: `users`, `projects`, `api_contexts`, `prompt_templates`, `settings`, `runs`, `candidates`, `decisions` (append-only), `audit_log`
- [ ] **`docs/API.md`**: contrato de endpoints que el frontend necesita ya

### Autenticación y permisos
- [ ] Login con JWT + bcrypt, `GET /auth/me`
- [ ] `require_role()` con Admin, QA Auditor y Observer
- [ ] Seed del usuario admin
- [ ] CRUD de `/users` (Admin)

### Endpoints
- [ ] `POST /projects` (con subida del OpenAPI), `PUT/GET /projects`
- [ ] `POST /projects/{id}/runs` (202 + `BackgroundTasks`, usando `execute_run` de `INTEGRATION.md §1.1`)
- [ ] `GET /runs/{id}` (con `report.stages[]`, `counts`, `status`) y listado de runs por proyecto
- [ ] `GET /runs/{id}/candidates?status=`
- [ ] `POST /candidates/{id}/decision` (justificación obligatoria al rechazar, solo `pending_review`, guarda `review_time_ms`)
- [ ] `GET /audit` y filtro por `run_id`
- [ ] `GET /metrics/project/{id}` y `GET /metrics/compare?runs=`
- [ ] `GET/PUT /settings/llm`, `/settings/thresholds`, CRUD `/prompts`
- [ ] **`GET /candidates/export?run_id=`** (JSON y CSV; lo necesitan los experimentos)
- [ ] Tests de RBAC por endpoint

### API demo (`sut-demo/`) — bloquea RQ1–RQ3 sobre la demo
- [ ] Catálogo con `GET /search` (`q`, `limit`, `page`, `sort`, `category`), datos deterministas
- [ ] 8–10 fallos activables con `FAULTS=` (`ignore_limit`, `wrong_total`, `page_off_by_one`, `sort_unstable`, `filter_or_instead_of_and`, `drops_last_page_item`…), todos observables con GET
- [ ] Puerto por línea de comandos y `GET /health`
- [ ] `/openapi.json` con descripciones, ejemplos, enums y rangos
- [ ] Suite pytest tradicional (`SUT_BASE_URL`) para la demo y, si hay tiempo, para PokeAPI y Crossref

### Infraestructura y despliegue
- [ ] `infra/docker-compose.yml` (dev: mongo, backend, frontend, sut-demo)
- [ ] `ci.yml`: ruff, pytest y build del frontend
- [ ] Instancia EC2 t3.medium, security group y subdominio DuckDNS
- [ ] `docker-compose.prod.yml` + Nginx + HTTPS (certbot)
- [ ] `deploy.yml`: push a `main` → GHCR → SSH a EC2
- [ ] Backup diario `mongodump` → S3 (retención 7 días) y CloudWatch básico
- [ ] Volumen o descarga en build del modelo de fastembed

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
- [x] Selector de proyecto (iteración activa = la más reciente)

### Pendiente — frontend
- [ ] Selector de iteración (hoy se abre siempre la más reciente) y costo en dinero por run (hoy solo tokens)
- [ ] **Conectar al backend real** y quitar los mocks (bloqueado por Nestor)
- [ ] Cambiar `gen:types` para usar `/openapi.json` y retirar `src/api/run.ts` (tipos de Run escritos a mano)
- [ ] ESLint + Prettier (`npm run lint`) y pruebas de componentes
- [ ] Revisar la vista móvil y la accesibilidad con lector de pantalla

> Los endpoints que el frontend asume y que Nestor debe confirmar: `POST /auth/login` (`{email, password}` → `{access_token, user}`), `GET /auth/me`, `GET /projects/{id}/runs`, `GET /metrics/compare?runs=`, `GET/POST/PATCH /users`, `GET/PUT /settings/llm` y `/settings/thresholds`, `GET/POST /prompts`. Ver `frontend/src/api/client.ts`.
>
> Matiz sobre roles: el plan solo deja decidir y lanzar iteraciones al QA; por indicación de Isaac, el Admin también puede (control total) y el Observador solo lee. El backend debe aplicar la misma regla.

> Desviación del plan: no se usó shadcn/ui, React Router ni TanStack Query/MSW; se usan Tailwind, rutas por hash y un mock propio. Se puede migrar si el equipo lo prefiere.

### Pendiente — experimentos y paper
- [ ] **MRs manuales** (5–8 por API) en `experiments/manual_mrs/{demo,pokeapi,crossref}/`, escritas **sin mirar** las generadas por MetaREST; validar con `mrexp mutants --manual`
- [ ] Etiquetado de validez (RQ1) como segundo etiquetador, según `experiments/LABELING.md`
- [ ] Agendar y ejecutar **SUS** (10 ítems, ≥ 5 participantes) — RQ4
- [ ] Figuras del paper a partir de `experiments/results/`

---

## Riesgos activos

| Riesgo | Impacto | Acción propuesta |
|---|---|---|
| Backend de plataforma sin publicar | Bloquea frontend real, despliegue, export y RQ3 | Nestor sube lo que tenga a `develop` hoy y publica `docs/API.md` |
| `sut-demo/` inexistente | Sin RQ3 ni resultados sobre la API demo | Priorizar una primera versión con 3–4 fallos para desbloquear a Daniel |
| Feature freeze el lun 16 | Poco margen para integrar | Acordar el contrato de endpoints hoy; el frontend ya espera los de `PLAN.md §1.4` |
| Sin participantes para el SUS | RQ4 incompleto | Isaac agenda sesiones esta semana |
