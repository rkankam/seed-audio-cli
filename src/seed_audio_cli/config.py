from __future__ import annotations

import os
from pathlib import Path

DEFAULT_API_URL = "https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create"


def _dotenv_value(name: str) -> str | None:
    dotenv_path = Path.cwd() / ".env"
    if not dotenv_path.is_file():
        return None

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


def _setting(name: str, default: str | None = None) -> str | None:
    return os.getenv(name) or _dotenv_value(name) or default


def api_url() -> str:
    return _setting("BYTEPLUS_SEED_AUDIO_URL", DEFAULT_API_URL) or DEFAULT_API_URL


def api_key(required: bool = True) -> str | None:
    value = _setting("BYTEPLUS_API_KEY")
    if required and not value:
        raise RuntimeError(
            "BYTEPLUS_API_KEY is required for provider calls; "
            + "set it in the environment or .env in the current working directory. "
            + "It is not accepted as a CLI argument."
        )
    return value
