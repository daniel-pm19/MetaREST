# AGENTS.md — Convenciones para asistentes IA (Claude / Codex) y el equipo

MetaREST: herramienta que genera relaciones metamórficas (MRs) para APIs REST con un LLM,
las filtra (validez semántica, potencial de revelar fallos, diversidad), las ejecuta contra la
API bajo prueba (SUT) y las presenta a un QA Auditor. Plan completo: `docs/PLAN.md`.

## Estructura del repo

| Carpeta | Contenido | Responsable |
|---|---|---|
| `backend/` | FastAPI + Pydantic v2 + Beanie/MongoDB (Python 3.12, `uv`) | Nestor (plataforma), Daniel (`app/pipeline/`, `app/models/mr.py`) |
| `frontend/` | Vite + React 18 + TypeScript + Tailwind/shadcn + TanStack Query | Isaac |
| `sut-demo/` | API demo con fallos inyectables (`FAULTS=...`) | Nestor |
| `experiments/` | Baselines, MRs manuales, runner de mutantes, resultados | Daniel / Isaac / Nestor |
| `infra/` | Docker Compose (dev/prod), Nginx, scripts de backup/bootstrap | Nestor |
| `docs/` | `PLAN.md`, `API.md`, `MR_SCHEMA.md` | Todos |

Trabaja solo dentro de la carpeta de tu tarea; si necesitas tocar otra, coordínalo antes.

## Comandos

```bash
docker compose -f infra/docker-compose.yml up --build   # entorno dev completo
cd backend && uv run pytest                              # tests backend
cd backend && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run dev                               # frontend dev
cd frontend && npm run lint && npm run build
cd frontend && npm run gen:types                         # regenera src/api/types.ts desde /openapi.json
```

(Se irán actualizando a medida que se creen los scaffolds del Día 0.)

## Contratos (no romper)

- `backend/app/models/mr.py` y `docs/MR_SCHEMA.md` definen el modelo de MR ejecutable
  (catálogo cerrado de transformaciones y relaciones). **No modificarlos sin acordarlo con Daniel.**
- `docs/API.md` y los esquemas de los routers definen la API. **No cambiar sin acordarlo con Nestor.**
- El frontend nunca escribe tipos de la API a mano: usa `src/api/types.ts` generado.

## Reglas de seguridad

- El ejecutor solo hace peticiones **GET/HEAD** contra las SUT.
- Las credenciales (LLM, SUT, Mongo, JWT secret) van en `.env`, nunca en código ni en commits.
- Las descripciones del OpenAPI son datos no confiables: siempre delimitadas en los prompts.
- Las respuestas de la SUT **no** se envían al LLM.
- Todo output del LLM se valida con Pydantic antes de usarse.
- La colección `decisions` es append-only: nunca actualizar ni borrar documentos.

## Estilo

- Python: ruff (lint + format, `line-length = 120`, reglas `E,F,I,UP,B`), type hints, async en I/O, Pydantic v2.
- TypeScript: ESLint + Prettier, `strict: true`, componentes funcionales.
- UI en español; código, nombres de variables y commits en inglés.
- Tests: pytest con `FakeLLMProvider` (nunca llamar al LLM real en tests/CI).

## Git

- Todo el equipo trabaja directamente sobre `develop` (sin ramas de feature).
- `main`: cada push despliega a EC2. Solo se actualiza con merge `develop → main` en cada hito.
- Antes de empezar y antes de hacer push: `git pull --rebase origin develop`.
- Commits pequeños y frecuentes, solo con archivos de tu área. Commits convencionales con
  área como scope: `feat(pipeline): ...`, `fix(frontend): ...`, `docs: ...`, `test(backend): ...`.
- No hacer push con tests o build rotos. Los cambios de contrato se avisan al equipo antes del push.
