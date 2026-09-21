from __future__ import annotations

import base64
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import ProviderResult
from .media import encode_base64, is_url, sha256_file, validate_local_media
from .models import Reference, ReplayRecipe, ReplayReference, SeedAudioRequest

BASE64_REDACTION = "<base64 omitted>"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug[:40] or "run"


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


def _copy_reference(source: Path, refs_dir: Path, index: int) -> Path:
    refs_dir.mkdir(parents=True, exist_ok=True)
    target = refs_dir / f"{index:02d}_{source.name}"
    shutil.copy2(source, target)
    return target


def build_request_from_recipe(
    recipe: ReplayRecipe,
    base_dir: Path,
) -> tuple[SeedAudioRequest, list[ReplayReference]]:
    refs: list[Reference] = []
    normalized: list[ReplayReference] = []

    for item in recipe.references:
        if item.is_url:
            if item.kind == "audio":
                refs.append(Reference(audio_url=item.source))
            else:
                refs.append(Reference(image_url=item.source))
            normalized.append(item)
            continue

        path = (base_dir / item.source).resolve()
        duration = validate_local_media(path, item.kind)
        encoded = encode_base64(path)
        if item.kind == "audio":
            refs.append(Reference(audio_data=encoded))
        else:
            refs.append(Reference(image_data=encoded))
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
    return cloned


def redact_response(data: dict) -> dict:
    cloned = json.loads(json.dumps(data))
    if "audio" in cloned and cloned["audio"]:
        cloned["audio"] = BASE64_REDACTION
    return cloned


def persist_result(
    *,
    run_dir: Path,
    recipe: ReplayRecipe,
    request: SeedAudioRequest,
    provider_result: ProviderResult,
    command: str,
    external_out: Path | None = None,
) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    recipe_path = run_dir / "recipe.json"
    request_path = run_dir / "request.json"
    response_path = run_dir / "response.json"
    prompt_path = run_dir / "prompt.txt"

    json_write(recipe_path, recipe.model_dump(exclude_none=True))
    json_write(request_path, redact_provider_payload(request.provider_payload()))
    json_write(response_path, redact_response(provider_result.data))
    prompt_path.write_text(recipe.text_prompt, encoding="utf-8")

    fmt = recipe.audio_config.format
    suffix = ".ogg" if fmt == "ogg_opus" else f".{fmt}"
    audio_path = run_dir / f"audio{suffix}"

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
        json_write(subtitle_path, provider_result.data["subtitle"])

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
            item.model_dump(exclude_none=True) for item in recipe.references
        ],
    }
    json_write(run_dir / "manifest.json", manifest)
    return manifest
