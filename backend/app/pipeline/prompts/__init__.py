"""Versioned prompt templates.

A template is identified by ``<name>_<version>`` (e.g. ``gen_v1``) and made of two
Jinja2 files: ``<id>.system.j2`` and ``<id>.user.j2``. Every generated MR stores the
prompt id in its provenance, so runs made with different prompts can be compared.
The Administrator may later override a template's text from the database
(``PromptTemplate.from_strings``); built-in files are the defaults.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

PROMPTS_DIR = Path(__file__).parent
_ENV = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=False)

# Tags used to delimit untrusted data inside prompts.
UNTRUSTED_TAGS = ("api_spec", "mr")
_TAG = re.compile(r"</?\s*(" + "|".join(UNTRUSTED_TAGS) + r")\s*>", re.IGNORECASE)


def neutralize_delimiters(text: str) -> str:
    """Replace any <api_spec>/<mr> tag inside untrusted text, so it cannot close its delimiter."""
    return _TAG.sub(lambda m: f"[{m.group(1).lower()}]", text)


@dataclass(frozen=True)
class RenderedPrompt:
    prompt_id: str
    system: str
    user: str


@dataclass(frozen=True)
class PromptTemplate:
    prompt_id: str
    system_source: str
    user_source: str

    @classmethod
    def builtin(cls, prompt_id: str) -> PromptTemplate:
        system = PROMPTS_DIR / f"{prompt_id}.system.j2"
        user = PROMPTS_DIR / f"{prompt_id}.user.j2"
        if not system.is_file() or not user.is_file():
            raise KeyError(f"unknown prompt template {prompt_id!r}")
        return cls(prompt_id, system.read_text(encoding="utf-8"), user.read_text(encoding="utf-8"))

    @classmethod
    def from_strings(cls, prompt_id: str, system: str, user: str) -> PromptTemplate:
        return cls(prompt_id, system, user)

    def render(self, **variables: Any) -> RenderedPrompt:
        return RenderedPrompt(
            prompt_id=self.prompt_id,
            system=_ENV.from_string(self.system_source).render(**variables).strip(),
            user=_ENV.from_string(self.user_source).render(**variables).strip(),
        )


def available_prompts() -> list[str]:
    return sorted(p.name.removesuffix(".system.j2") for p in PROMPTS_DIR.glob("*.system.j2"))
