# Contrato HTTP del backend de Nestor

Implementación local sobre `0904ff6`, 15-nov-2026. La API usa los modelos del pipeline
de Daniel sin cambiarlos y coincide con las rutas de `frontend/src/api/client.ts`.
Documentación ejecutable: `/docs` y `/openapi.json`. Prefijo local: ninguno.
Detrás del Nginx de `infra/`, el navegador usa `/api` y el proxy elimina ese prefijo.

## Arranque

```powershell
cd backend
uv sync --locked
Copy-Item .env.example .env
# Edita .env: configura JWT_SECRET aleatorio (>=32 caracteres), ADMIN_EMAIL y
# ADMIN_PASSWORD (12–72 bytes UTF-8), y una MongoDB accesible.
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

MongoDB debe responder al arrancar. Las colecciones e índices se crean con Beanie;
el servidor no sustituye silenciosamente Mongo por memoria. El seed de admin
solo inserta un correo inexistente; no cambia contraseñas ni roles existentes.
Las claves del LLM y los headers de la SUT se leen del entorno/`.env`, nunca se
guardan en los documentos de configuración ni se envían al navegador.

Pruebas sin servicios externos: `uv run pytest -q`. Las pruebas de plataforma usan
`mongomock-motor`; con `TEST_MONGODB_URI` usan Mongo real en una base temporal por
prueba y la eliminan al terminar. CI configura esta variable para Mongo 7.
Los temporales de pytest se crean en `backend/.pytest_tmp/`, en una carpeta única
por ejecución que se limpia al terminar. Así no dependen de permisos heredados de
`AppData/Local/Temp/pytest-of-*`. Un `--basetemp` explícito sigue teniendo prioridad.
La caché persistente de pytest está desactivada para evitar directorios con ACL
incompatibles entre usuarios o ejecuciones del asistente y del terminal.

## Acceso

`POST /auth/login` recibe `{"email":"...","password":"..."}` y devuelve
`{"access_token":"...","token_type":"bearer","user":{"id":"...","name":"...","email":"...","role":"admin","active":true}}`.
El resto usa `Authorization: Bearer <token>`, excepto `GET /health`.

Roles: `admin`, `qa`, `observer`. Admin y QA pueden registrar proyectos, ejecutar
el pipeline, decidir y exportar; Observer solo lee. Configuración, prompts y
usuarios son exclusivos de Admin. Cada petición comprueba el usuario activo y
su rol actual en Mongo: cambiar un rol o desactivar una cuenta afecta también
a tokens anteriores. JWT HS256 expira según `JWT_EXPIRATION_MINUTES`, sin refresh.
No hay credenciales predefinidas. Publicar el login en internet requiere HTTPS
y límites de peticiones en el proxy.

## Rutas

| Método y ruta | Acceso | Contrato |
|---|---|---|
| `GET /health` | Público | `{"status":"ok"}`; liveness, Mongo se comprueba en startup |
| `GET /auth/me` | Todos | Usuario sin hash ni contraseña |
| `GET /users` | Admin | Lista de usuarios |
| `POST /users` | Admin | `{name,email,role,password}` → usuario, 201; correo duplicado: 409 |
| `PATCH /users/{id}` | Admin | `{role?,active?}` → usuario; no se permite modificar la propia cuenta |
| `DELETE /users/{id}` | Admin | Desactiva, no borra historial; 204 |
| `GET /projects` | Todos | Lista `{id,name,base_url,endpoints,created_at}` |
| `GET /projects/{id}` | Todos | Un proyecto |
| `POST /projects` | Admin/QA | JSON `{name,base_url,openapi}` → proyecto, 201 |
| `PUT /projects/{id}` | Admin/QA | Sustitución de la configuración del proyecto |
| `GET /projects/{id}/runs` | Todos | Lista de runs por número de iteración |
| `POST /projects/{id}/runs` | Admin/QA | Sin body; run en estado running, 202; activo duplicado: 409 |
| `GET /runs/{id}` | Todos | Estado, etapas, tokens y conteos actuales |
| `GET /runs/{id}/candidates?status=` | Todos | `MRCandidate[]`, filtro opcional por estado |
| `POST /candidates/{id}/decision` | Admin/QA | `{decision,justification?,review_time_ms?}`; 201 |
| `GET /audit?run_id=` | Todos | Decisiones con autor, fecha, tiempo y provenance |
| `GET /metrics/project/{id}` | Todos | Métricas de las iteraciones del proyecto |
| `GET /metrics/compare?runs=id1,id2` | Todos | Métricas por run, hasta 20 ids |
| `GET /candidates/export?run_id=&format=json` | Admin/QA | `{settings,report,candidates}` para `mrexp`; incluye descartadas |
| `GET /candidates/export?run_id=&format=csv` | Admin/QA | CSV con estado, motivo, veredicto y score |
| `GET/PUT /settings/llm` | Admin | `LLMSettings` validado; solo Anthropic/Gemini en producción |
| `GET/PUT /settings/thresholds` | Admin | `FilterSettings` validado; campos omitidos toman valores por defecto |
| `GET/PUT /settings/pipeline` | Admin | `PipelineSettings` completo, incluida selección de prompts |
| `GET /prompts` | Admin | Built-ins y versiones propias con `{id,kind,system,user,editable}` |
| `POST /prompts` | Admin | Nueva versión con id único, 201 |
| `PUT /prompts/{id}` | Admin | 409: los cambios requieren crear una versión con otro id |
| `DELETE /prompts/{id}` | Admin | Solo versiones propias no configuradas ni utilizadas; 204 |

El upload es texto OpenAPI JSON/YAML en el campo JSON `openapi`, como ya envía el
frontend; no multipart. Campos opcionales del proyecto: `auth_env_key` (nombre
`SUT_*` de una variable con headers JSON), `timeout`, `max_concurrency`,
`min_interval`. Por defecto 10 s, 4 y 0 s. La URL debe ser HTTP(S) sin credenciales,
query ni fragmento. Las URLs locales son necesarias para la demo: esta aplicación
está pensada para usuarios QA de confianza, no como proxy HTTP público.

## Ejecuciones y persistencia

`BackgroundTasks` usa directamente `run_pipeline`, `create_provider`,
`FastEmbedEmbedder` y `SUTClient` del equipo. Cada run guarda un snapshot de
configuración, proyecto y prompts. Se persiste el progreso al empezar/terminar
cada etapa; el cliente consulta `GET /runs/{id}`. Se conservan todas las candidatas,
incluidas las descartadas, y el contexto extraído. Fastembed tiene caché por
proceso y almacenamiento configurable; la primera ejecución descarga el modelo.

Un solo worker/proceso para este MVP: no hay cola distribuida. Al reiniciar, los
runs que seguían `running` se marcan `failed` y se indica que fueron interrumpidos.
El cierre de una ejecución termina en `awaiting_review` o `failed` según el reporte.
Una violación de una MR no implica un fallo del propio pipeline.

## Decisiones y métricas

Solo una candidata `pending_review` puede recibir decisión. Rechazar requiere
justificación no vacía. Un índice único en `decisions.candidate_id` hace que dos
decisiones concurrentes produzcan un éxito y un 409. La decisión se inserta antes
de actualizar el estado materializado de la candidata; las lecturas y el export
aplican siempre la decisión persistida como fuente de verdad. Así una interrupción
entre ambas escrituras no pierde la decisión ni permite sobrescribirla.

La API no expone actualización ni borrado de decisiones. Para inmutabilidad frente
a accesos directos a la base, Mongo necesita permisos que prohíban update/delete
sobre `decisions` y `audit_log`; la aplicación por sí sola no protege contra un
administrador de la base de datos.

`confirmed_faults` conserva el nombre esperado por el frontend: cuenta candidatas
aceptadas cuyo veredicto es `violation`. No cuenta defectos independientes ni
demuestra una confirmación manual del defecto de la SUT. La tasa de aceptación
usa aceptadas/(aceptadas+rechazadas); es null si no se ha decidido ninguna.
`avg_combined` es 0–100; `avg_review_ms` excluye tiempos no registrados.

## Estados HTTP y límites

401 sesión inválida, 403 rol insuficiente, 404 recurso inexistente, 409 conflicto,
413 spec mayor al máximo configurado, 422 formato/valores inválidos. Los errores
de validación no devuelven el valor de entrada, para evitar reflejar contraseñas.
No hay recuperación de contraseña ni paginación de listas en este MVP.

## Pendientes operativos

Las 25 pruebas de plataforma también pasaron contra un servidor MongoDB 7 real,
aislado en loopback. El arranque con Docker debe verificarse en un equipo con el
motor Docker activo. Estas pruebas no prueban redes de contenedores, HTTPS, AWS,
cuotas del LLM ni la descarga real de embeddings. Los tests no llaman a un LLM real.
