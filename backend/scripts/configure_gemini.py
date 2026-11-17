"""Preview/apply Gemini to existing platform settings without rewriting run history.

From backend: python -m scripts.configure_gemini [--apply]
Only provider-specific models, verification effort and RPM take Gemini defaults.
Common LLM options, filters and prompts are retained. Existing Gemini settings
are left intact, including custom models, unless they still contain Claude model
names from a provider switch. No LLM calls are made.
"""

import argparse
import asyncio

from pymongo.errors import PyMongoError

from app.models.platform import SettingsRecord
from app.pipeline.llm.config import LLMSettings

_PROVIDER_FIELDS = {"provider", "generation_model", "verification_model", "verification_effort", "requests_per_minute"}


async def configure_gemini(*, apply: bool = False) -> dict:
    record = await SettingsRecord.get("pipeline")
    if record is None:
        raise RuntimeError("Inicializa la base de datos antes de configurar el proveedor")
    current = record.pipeline.llm
    stale_models = {
        name
        for name in ("generation_model", "verification_model")
        if getattr(current, name).removeprefix("models/").startswith("claude-")
    }
    if current.provider == "gemini" and not stale_models:
        return {"changed": False, "applied": False, "provider": "gemini"}
    options = current.model_dump(exclude=_PROVIDER_FIELDS)
    if current.provider == "gemini":
        # Keep custom Gemini-compatible model names; replace only the stale ones.
        options.update(
            {
                name: getattr(current, name)
                for name in ("generation_model", "verification_model")
                if name not in stale_models
            }
        )
    proposed = LLMSettings(provider="gemini", **options)
    if apply:
        # Do not overwrite settings changed by an administrator after this read.
        result = await SettingsRecord.get_motor_collection().update_one(
            {"_id": record.id, "pipeline.llm": current.model_dump(mode="json")},
            {"$set": {"pipeline.llm": proposed.model_dump(mode="json")}},
        )
        if result.matched_count != 1:
            raise RuntimeError("La configuración cambió durante la actualización; vuelve a intentarlo")
    return {
        "changed": True,
        "applied": apply,
        "previous_provider": current.provider,
        "provider": proposed.provider,
        "generation_model": proposed.generation_model,
        "verification_model": proposed.verification_model,
    }


async def main() -> None:
    import json

    from app.config import Settings
    from app.db import initialize_database

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist the change; default is preview only")
    args = parser.parse_args()
    settings = Settings()
    client = await initialize_database(settings)
    try:
        print(json.dumps(await configure_gemini(apply=args.apply), ensure_ascii=False, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except PyMongoError:
        raise SystemExit("No se pudo acceder a MongoDB. Arranca la base y revisa la configuración local.") from None
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
