from __future__ import annotations

import os

DEFAULT_API_URL = "https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create"


def api_url() -> str:
    return os.getenv("BYTEPLUS_SEED_AUDIO_URL", DEFAULT_API_URL)


def api_key(required: bool = True) -> str | None:
    value = os.getenv("BYTEPLUS_API_KEY")
    if required and not value:
        raise RuntimeError(
            "BYTEPLUS_API_KEY is required for provider calls. "
            "It is intentionally not accepted as a CLI argument."
        )
    return value
