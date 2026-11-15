# MetaREST

El modelo de generación (Sonnet 5.5) y el de verificación (Haiku 5.5);
la salida estructurada con output_config.format en lugar de forzar una herramienta, y por eso existe wire.py;
el nivel de razonamiento (effort), max_tokens con streaming, el respaldo del servidor cuando el modelo se niega a responder, el máximo de 20 MRs por run, el idioma del prompt, y el timeout con reintentos.

## Backend HTTP y API demo 

El backend HTTP ya conecta el pipeline existente con proyectos, ejecuciones,
revisión, usuarios y export. Consulta [docs/API.md](docs/API.md) para configurar
MongoDB, `.env`, autenticación y contratos compatibles con el frontend.

```powershell
cd backend
uv sync --locked
# Configura .env con Mongo accesible, JWT_SECRET y el seed del admin.
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

La [API demo](sut-demo/README.md) incluye 8 fallos activables y una suite
tradicional con `SUT_BASE_URL`. Desde `backend`,
`uv run python -m scripts.check_demo_baseline` verifica el original y cada fallo.

Los manifiestos locales/producción, la CI y las recetas operativas están en
[infra/README.md](infra/README.md). Su existencia no implica un despliegue en AWS.
Estado local detallado: [docs/CHECKLIST.md](docs/CHECKLIST.md).
