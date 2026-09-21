from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from urllib.parse import urlparse

from mutagen import File as MutagenFile

MAX_MEDIA_BYTES = 10 * 1024 * 1024
AUDIO_SUFFIXES = {".wav", ".mp3", ".pcm", ".ogg", ".opus"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_local_media(path: Path, kind: str) -> float | None:
    if not path.is_file():
        raise ValueError(f"reference does not exist or is not a file: {path}")

    size = path.stat().st_size
    if size > MAX_MEDIA_BYTES:
        raise ValueError(f"reference exceeds the 10 MB provider limit: {path}")

    suffix = path.suffix.lower()
    allowed = AUDIO_SUFFIXES if kind == "audio" else IMAGE_SUFFIXES
    if suffix not in allowed:
        raise ValueError(
            f"unsupported {kind} reference extension {suffix!r}; "
            f"allowed: {', '.join(sorted(allowed))}"
        )

    if kind != "audio" or suffix == ".pcm":
        return None

    try:
        media = MutagenFile(path)
        if media is None or media.info is None:
            return None
        duration = float(media.info.length)
    except Exception:
        return None

    if duration > 30.0:
        raise ValueError(
            f"audio reference exceeds the 30 second provider limit "
            f"({duration:.3f}s): {path}"
        )
    return duration


def encode_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")
