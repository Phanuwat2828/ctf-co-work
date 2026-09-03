"""Data-driven provider registry — manages providers.json.

A provider is: name, kind (which solver backend it maps to), base URL,
API key, and the list of model IDs to run. The web UI's "Providers" panel
adds/removes these; model specs are derived from them at runtime.

Storage: providers.json in the project root (gitignored).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROVIDERS_FILE = Path(__file__).resolve().parent.parent / "providers.json"

# Kind -> spec prefix (the `provider` part of a model spec).
KIND_TO_PREFIX: dict[str, str] = {
    "claude-sdk": "claude-sdk",
    "codex": "codex",
    "google": "google",
    "azure": "azure",
    "zen": "zen",
    "bedrock": "bedrock",
    "openai_compatible": "custom",
    "anthropic": "custom",
}

KNOWN_KINDS = list(KIND_TO_PREFIX)

# API formats shown in the "Add provider" form. Maps format -> (label, kind).
API_FORMATS: list[tuple[str, str]] = [
    ("openai_chat", "OpenAI Chat Completions (/v1/chat/completions)"),
    ("openai_responses", "OpenAI Responses (/v1/responses)"),
    ("anthropic", "Anthropic Messages (/v1/messages)"),
    ("google", "Google Generative Language (/v1beta/models)"),
    ("claude_sdk", "Claude SDK (subscription / ANTHROPIC key)"),
    ("codex", "Codex CLI (OPENAI key)"),
]

FORMAT_TO_KIND: dict[str, str] = {
    "openai_chat": "openai_compatible",
    "openai_responses": "openai_compatible",
    "anthropic": "anthropic",
    "google": "google",
    "claude_sdk": "claude-sdk",
    "codex": "codex",
}

KIND_TO_FORMAT: dict[str, str] = {v: k for k, v in FORMAT_TO_KIND.items()}

# Seed the file with these on first run so the UI shows them.
DEFAULT_PROVIDERS: list[dict[str, Any]] = [
    {
        "name": "Anthropic",
        "kind": "claude-sdk",
        "base_url": "https://api.anthropic.com",
        "api_key": "",
        "models": ["claude-opus-4-6/medium", "claude-opus-4-6/max"],
    },
    {
        "name": "OpenAI",
        "kind": "codex",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "models": ["gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"],
    },
    {
        "name": "Google",
        "kind": "google",
        "base_url": "https://generativelanguage.googleapis.com",
        "api_key": "",
        "models": ["gemini-3-flash-preview"],
    },
]


@dataclass
class ProviderConfig:
    name: str
    kind: str = "openai_compatible"
    api_format: str = "openai_chat"
    base_url: str = ""
    api_key: str = ""
    models: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProviderConfig:
        kind = str(d.get("kind") or "").strip()
        fmt = str(d.get("api_format") or "").strip()
        if fmt:
            kind = FORMAT_TO_KIND.get(fmt, kind or "openai_compatible")
        elif not kind:
            kind = "openai_compatible"
        return cls(
            name=str(d.get("name", "")).strip(),
            kind=kind,
            api_format=fmt or KIND_TO_FORMAT.get(kind, "openai_chat"),
            base_url=str(d.get("base_url", "")).strip(),
            api_key=str(d.get("api_key", "")).strip(),
            models=[str(m).strip() for m in (d.get("models") or []) if str(m).strip()],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "api_format": self.api_format,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "models": self.models,
        }


def _read_file() -> list[dict[str, Any]]:
    if not PROVIDERS_FILE.exists():
        PROVIDERS_FILE.write_text(json.dumps(DEFAULT_PROVIDERS, indent=2) + "\n", encoding="utf-8")
        return DEFAULT_PROVIDERS
    try:
        data = json.loads(PROVIDERS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not parse providers.json — using defaults")
        return DEFAULT_PROVIDERS


def load_providers() -> list[ProviderConfig]:
    return [ProviderConfig.from_dict(d) for d in _read_file()]


def save_providers(providers: list[ProviderConfig]) -> None:
    PROVIDERS_FILE.write_text(
        json.dumps([p.to_dict() for p in providers], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def find_provider(name: str) -> ProviderConfig | None:
    for p in load_providers():
        if p.name.lower() == name.lower():
            return p
    return None


def model_specs_from_providers(providers: list[ProviderConfig] | None = None) -> list[str]:
    """Derive the model-spec lineup from providers.

    - claude-sdk/*  -> claude-sdk/<model>          (Claude Agent SDK solver)
    - codex/*        -> codex/<model>              (Codex solver)
    - google/azure/zen/bedrock -> <kind>/<model>   (Pydantic AI solver)
    - openai_compatible / anthropic -> custom/<name>/<model>  (Pydantic AI, custom base URL)
    """
    providers = providers if providers is not None else load_providers()
    specs: list[str] = []
    for p in providers:
        if not p.models or not p.name:
            continue
        prefix = KIND_TO_PREFIX.get(p.kind, "custom")
        for m in p.models:
            if p.kind in ("openai_compatible", "anthropic"):
                specs.append(f"{prefix}/{p.name}/{m}")
            else:
                specs.append(f"{prefix}/{m}")
    return specs


def has_any_key(providers: list[ProviderConfig] | None = None) -> bool:
    providers = providers if providers is not None else load_providers()
    return any(p.api_key for p in providers)