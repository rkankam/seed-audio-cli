from __future__ import annotations

import base64
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .client import ProviderResult
from .media import encode_base64, is_url, sha256_file, validate_local_media
from .models import Reference, ReplayRecipe, ReplayReference, SeedAudioRequest

BASE64_REDACTION = "<base64 omitted>"
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug[:40] or "run"


def audio_artifact_filename(audio_format: str, prefix: str | None = None) -> str:
    suffix = ".ogg" if audio_format == "ogg_opus" else f".{audio_format}"
    if prefix:
        return f"{slugify(prefix)}_audio{suffix}"
    return f"audio{suffix}"


def make_run_dir(root: Path, name: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    path = root / f"{stamp}_{slugify(name)}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def json_write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def redact_url(value: str) -> str:
    """Remove URL userinfo, query parameters, and fragments from a display value."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return "<redacted URL>"
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return value
    safe_netloc = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, safe_netloc, parts.path, "", ""))


def redact_urls_in_text(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ".,;:!?)]}":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        return redact_url(raw) + trailing

    return _URL_RE.sub(replace, value)


def redact_sensitive_values(value: Any) -> Any:
    """Copy JSON-shaped data while redacting URLs embedded in string values."""
    if isinstance(value, dict):
        return {
            redact_urls_in_text(key) if isinstance(key, str) else key: redact_sensitive_values(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    if isinstance(value, str):
        return redact_urls_in_text(value)
    return value


def redact_recipe(recipe: ReplayRecipe) -> ReplayRecipe:
    references = []
    for item in recipe.references:
        if not item.is_url:
            references.append(item)
            continue
        safe_source = redact_url(item.source)
        references.append(
            item.model_copy(
                update={
                    "source": safe_source,
                    "url_redacted": item.url_redacted or safe_source != item.source,
                }
            )
        )
    return recipe.model_copy(update={"references": references})


def _resolve_replay_reference(base_dir: Path, source: str) -> Path:
    relative = Path(source)
    windows_path = PureWindowsPath(source)
    if relative.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError("local replay reference must be relative to its run directory")
    if ".." in relative.parts or ".." in windows_path.parts:
        raise ValueError("local replay reference cannot contain parent traversal")

    try:
        root = base_dir.resolve(strict=True)
        resolved = (root / relative).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            f"local replay reference does not exist or cannot be resolved: {source}"
        ) from exc

    if not resolved.is_relative_to(root):
        raise ValueError("local replay reference resolves outside its run directory")
    if not resolved.is_file():
        raise ValueError(f"local replay reference is not a file: {source}")
    return resolved


def _copy_reference(source: Path, refs_dir: Path, index: int) -> Path:
    refs_dir.mkdir(parents=True, exist_ok=True)
    target = refs_dir / f"{index:02d}_{source.name}"
    shutil.copy2(source, target)
    return target


def build_request_from_recipe(
    recipe: ReplayRecipe,
    base_dir: Path,
    *,
    replay: bool = False,
) -> tuple[SeedAudioRequest, list[ReplayReference]]:
    refs: list[Reference] = []
    normalized: list[ReplayReference] = []
    replay_paths: list[Path] = []

    if replay:
        for item in recipe.references:
            if item.is_url:
                if item.url_redacted:
                    raise ValueError(
                        "remote reference URL was redacted for security and cannot be "
                        "replayed; provide a new valid URL with seed-audio gen --ref or --image"
                    )
                continue
            if item.sha256 is None or item.bytes is None:
                raise ValueError(
                    "local replay reference is missing integrity metadata "
                    "(sha256 and bytes); regenerate the run or provide a new reference"
                )
            replay_paths.append(_resolve_replay_reference(base_dir, item.source))

    replay_path_iter = iter(replay_paths)

    for item in recipe.references:
        if item.is_url:
            if item.kind == "audio":
                refs.append(Reference(audio_url=item.source))
            else:
                refs.append(Reference(image_url=item.source))
            normalized.append(item)
            continue

        path = (
            next(replay_path_iter)
            if replay
            else (base_dir / item.source).resolve()
        )
        if replay:
            actual_size = path.stat().st_size
            if actual_size != item.bytes:
                raise ValueError(
                    "local replay reference size mismatch: "
                    f"recorded {item.bytes} bytes, found {actual_size}"
                )
            actual_sha256 = sha256_file(path)
            if actual_sha256 != item.sha256:
                raise ValueError(
                    "local replay reference SHA-256 mismatch: "
                    f"recorded {item.sha256}, found {actual_sha256}"
                )
        duration = validate_local_media(path, item.kind)
        encoded = encode_base64(path)
        if item.kind == "audio":
            refs.append(Reference(audio_data=encoded))
        else:
            refs.append(Reference(image_data=encoded))
        if replay:
            normalized.append(item)
        else:
            normalized.append(
                item.model_copy(
                    update={
                        "sha256": sha256_file(path),
                        "bytes": path.stat().st_size,
                        "duration_seconds": duration,
                    }
                )
            )

    request = SeedAudioRequest(
        model=recipe.model,
        text_prompt=recipe.text_prompt,
        references=refs or None,
        audio_config=recipe.audio_config,
        watermark=recipe.watermark,
    )
    return request, normalized


def prepare_recipe(
    *,
    model: str,
    prompt: str,
    audio_refs: list[str],
    image_ref: str | None,
    audio_config,
    watermark,
    run_dir: Path | None,
) -> ReplayRecipe:
    if audio_refs and image_ref:
        raise ValueError("audio references and image reference cannot be mixed")
    if len(audio_refs) > 3:
        raise ValueError("at most 3 audio references are supported")

    inputs: list[tuple[str, str]] = [("audio", item) for item in audio_refs]
    if image_ref:
        inputs.append(("image", image_ref))

    replay_refs: list[ReplayReference] = []
    for index, (kind, source) in enumerate(inputs, start=1):
        if is_url(source):
            replay_refs.append(
                ReplayReference(kind=kind, source=source, is_url=True)
            )
            continue

        local = Path(source).expanduser().resolve()
        duration = validate_local_media(local, kind)
        if run_dir is not None:
            copied = _copy_reference(local, run_dir / "refs", index)
            relative = copied.relative_to(run_dir).as_posix()
            path_for_hash = copied
        else:
            relative = str(local)
            path_for_hash = local

        replay_refs.append(
            ReplayReference(
                kind=kind,
                source=relative,
                is_url=False,
                sha256=sha256_file(path_for_hash),
                bytes=path_for_hash.stat().st_size,
                duration_seconds=duration,
            )
        )

    return ReplayRecipe(
        model=model,
        text_prompt=prompt,
        references=replay_refs,
        audio_config=audio_config,
        watermark=watermark,
    )


def redact_provider_payload(payload: dict) -> dict:
    cloned = json.loads(json.dumps(payload))
    for ref in cloned.get("references", []):
        for key in ("audio_data", "image_data"):
            if key in ref:
                ref[key] = BASE64_REDACTION
    return redact_sensitive_values(cloned)


def redact_response(data: dict) -> dict:
    cloned = json.loads(json.dumps(data))
    if "audio" in cloned and cloned["audio"]:
        cloned["audio"] = BASE64_REDACTION
    return redact_sensitive_values(cloned)


def persist_result(
    *,
    run_dir: Path,
    recipe: ReplayRecipe,
    request: SeedAudioRequest,
    provider_result: ProviderResult,
    command: str,
    external_out: Path | None = None,
    artifact_prefix: str | None = None,
) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    recipe_path = run_dir / "recipe.json"
    request_path = run_dir / "request.json"
    response_path = run_dir / "response.json"
    prompt_path = run_dir / "prompt.txt"
    persisted_recipe = redact_recipe(recipe)

    json_write(recipe_path, persisted_recipe.model_dump(exclude_none=True))
    json_write(request_path, redact_provider_payload(request.provider_payload()))
    json_write(response_path, redact_response(provider_result.data))
    prompt_path.write_text(recipe.text_prompt, encoding="utf-8")

    audio_path = run_dir / audio_artifact_filename(
        recipe.audio_config.format,
        artifact_prefix,
    )

    audio_b64 = provider_result.data.get("audio")
    if audio_b64:
        try:
            audio_path.write_bytes(base64.b64decode(audio_b64, validate=True))
        except Exception as exc:
            raise ValueError("provider returned invalid Base64 audio") from exc
    else:
        url = provider_result.data.get("url")
        if not url:
            raise ValueError("provider response contained neither audio nor url")
        import httpx

        with httpx.Client(timeout=120.0) as client:
            response = client.get(url)
            response.raise_for_status()
            audio_path.write_bytes(response.content)

    if external_out is not None:
        external_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio_path, external_out)

    subtitle_path: Path | None = None
    if provider_result.data.get("subtitle") is not None:
        subtitle_path = run_dir / "subtitles.json"
        json_write(
            subtitle_path,
            redact_sensitive_values(provider_result.data["subtitle"]),
        )

    manifest = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "created_at": datetime.now(UTC).isoformat(),
        "command": command,
        "provider": "byteplus",
        "model": recipe.model,
        "request_id": provider_result.request_id,
        "provider_log_id": provider_result.provider_log_id,
        "duration_seconds": provider_result.data.get("duration"),
        "billing_duration_seconds": provider_result.data.get("original_duration"),
        "artifacts": {
            "audio": audio_path.name,
            "audio_sha256": sha256_file(audio_path),
            "prompt": prompt_path.name,
            "recipe": recipe_path.name,
            "request": request_path.name,
            "response": response_path.name,
            "subtitles": subtitle_path.name if subtitle_path else None,
        },
        "references": [
            item.model_dump(exclude_none=True)
            for item in persisted_recipe.references
        ],
    }
    json_write(run_dir / "manifest.json", redact_sensitive_values(manifest))
    return manifest
