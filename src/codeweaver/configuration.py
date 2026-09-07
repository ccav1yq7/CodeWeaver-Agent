"""User-owned configuration. A repository never supplies executable configuration implicitly."""

import os
import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Connector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,25}$")
    command: list[str] = Field(min_length=1)
    environment: list[str] = Field(default_factory=list)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Literal["openai", "anthropic", "demo"] = "openai"
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    key_env: str = "OPENAI_API_KEY"
    mode: Literal["review", "workspace", "read-only"] = "review"
    max_rounds: int = Field(default=20, ge=1, le=100)
    max_tools: int = Field(default=80, ge=1, le=500)
    max_output_tokens: int = Field(default=4096, ge=128, le=32768)
    context_chars: int = Field(default=100_000, ge=8000, le=500_000)
    command_timeout: int = Field(default=60, ge=1, le=600)
    request_timeout: int = Field(default=90, ge=1, le=600)
    deny_tools: list[str] = Field(default_factory=list)
    allow_commands: list[list[str]] = Field(default_factory=list)
    connectors: list[Connector] = Field(default_factory=list)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value):
        if value is None:
            return value
        url = urlsplit(value)
        if url.username or url.password or url.query or url.fragment or not url.hostname:
            raise ValueError("Provider URL must not contain credentials, query or fragment")
        if url.scheme != "https" and not (
            url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Provider URL requires HTTPS (HTTP is allowed only on loopback)")
        return value

    @field_validator("key_env")
    @classmethod
    def validate_key_name(cls, value):
        if not value.isidentifier():
            raise ValueError("key_env must name an environment variable, not contain a key")
        return value


def load_settings(path: Path | None = None, **overrides) -> Settings:
    data = tomllib.loads(path.read_text()) if path else {}
    provider = overrides.get("provider") or os.getenv("CODEWEAVER_PROVIDER") or data.get("provider", "openai")
    data["provider"] = provider
    data.setdefault("model", "claude-sonnet-4-20250514" if provider == "anthropic" else "gpt-4o-mini")
    data.setdefault("key_env", "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY")
    for key, env in (("model", "CODEWEAVER_MODEL"), ("base_url", "CODEWEAVER_BASE_URL")):
        if os.getenv(env):
            data[key] = os.environ[env]
    data.update({k: v for k, v in overrides.items() if v is not None})
    return Settings(**data)
