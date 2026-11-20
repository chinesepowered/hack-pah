"""Settings loaded from the environment (and a local, gitignored .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

try:  # trust the operating system's certificate store (works on laptops, CI and TLS-inspecting networks)
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # SingleStore. mysql://user:pass@host:3306/db uses the MySQL protocol;
    # https://user:pass@host/db (or http://...:9000 for the dev image) uses the Data API.
    singlestore_url: str = field(default_factory=lambda: _env("SINGLESTORE_URL"))
    singlestore_db: str = field(default_factory=lambda: _env("SINGLESTORE_DB", "capyteam"))

    # Superlinked SIE Serverless: every model call goes here.
    sie_api_key: str = field(default_factory=lambda: _env("SIE_API_KEY"))
    sie_base_url: str = field(default_factory=lambda: _env("SIE_BASE_URL", "https://api.superlinked.com"))
    model_agent: str = field(default_factory=lambda: _env("CAPY_MODEL_AGENT", "Qwen/Qwen3.8-27B-FP8"))
    model_coach: str = field(default_factory=lambda: _env("CAPY_MODEL_COACH", "Qwen/Qwen3.8-27B-FP8"))
    model_classify: str = field(default_factory=lambda: _env("CAPY_MODEL_CLASSIFY", "knowledgator/gliclass-instruct-large-v1.0"))
    model_extract: str = field(default_factory=lambda: _env("CAPY_MODEL_EXTRACT", "fastino/gliner2-large-v1"))
    model_guard: str = field(default_factory=lambda: _env("CAPY_MODEL_GUARD", "knowledgator/gliclass-instruct-large-v1.0"))
    model_embed: str = field(default_factory=lambda: _env("CAPY_MODEL_EMBED", "Qwen/Qwen3-Embedding-4B"))
    model_rerank: str = field(default_factory=lambda: _env("CAPY_MODEL_RERANK", "Qwen/Qwen3-Reranker-4B"))
    sie_generation_concurrency: int = field(default_factory=lambda: int(_env("SIE_GENERATION_CONCURRENCY", "4")))

    # Amplitude Agent Analytics (+ optional secret key for the export API).
    amplitude_api_key: str = field(default_factory=lambda: _env("AMPLITUDE_API_KEY"))
    amplitude_secret_key: str = field(default_factory=lambda: _env("AMPLITUDE_SECRET_KEY"))

    # Statsig rolls out agent versions.
    statsig_server_secret: str = field(default_factory=lambda: _env("STATSIG_SERVER_SECRET"))
    statsig_experiment: str = field(default_factory=lambda: _env("STATSIG_EXPERIMENT", "capyteam_agent_release"))

    # Airbyte (live mode). Agent SDK locally with a Stripe key, or hosted with an Airbyte application.
    airbyte_client_id: str = field(default_factory=lambda: _env("AIRBYTE_CLIENT_ID"))
    airbyte_client_secret: str = field(default_factory=lambda: _env("AIRBYTE_CLIENT_SECRET"))
    stripe_api_key: str = field(default_factory=lambda: _env("STRIPE_API_KEY"))

    # Where the agent's synthetic tools live. Firedrill sets these per drill; the
    # local sandbox serves the same invoke contract for development and races.
    stripe_invoke_url: str = field(default_factory=lambda: _env("STRIPE_INVOKE_URL"))
    quickbooks_invoke_url: str = field(default_factory=lambda: _env("QUICKBOOKS_INVOKE_URL"))
    gmail_invoke_url: str = field(default_factory=lambda: _env("GMAIL_INVOKE_URL"))

    # Runtime
    mode: str = field(default_factory=lambda: _env("CAPY_MODE", "practice"))
    agent_version: str = field(default_factory=lambda: _env("CAPY_AGENT_VERSION", ""))
    owner_id: str = field(default_factory=lambda: _env("CAPY_OWNER_ID", "owner-maya"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8787")))
    sandbox_port: int = field(default_factory=lambda: int(_env("CAPY_SANDBOX_PORT", "8790")))

    @property
    def amplitude_enabled(self) -> bool:
        return bool(self.amplitude_api_key) and _env("CAPY_AMPLITUDE", "1") != "0"


settings = Settings()
