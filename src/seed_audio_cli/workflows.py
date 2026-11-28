from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import AudioConfig, WatermarkConfig


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("workflow YAML must contain an object at the root")
    return data


def resolve_path(value: str, base: Path) -> str:
    if value.startswith(("http://", "https://")):
        return value
    return str((base / value).resolve())


def _expand_job(
    raw: dict[str, Any],
    *,
    base: Path,
    label: str,
) -> dict[str, Any]:
    item = dict(raw)
    has_prompt = bool(item.get("prompt"))
    has_prompt_file = bool(item.get("prompt_file"))
    if has_prompt == has_prompt_file:
        raise ValueError(f"{label} requires exactly one of prompt or prompt_file")

    if has_prompt_file:
        prompt_path = (base / str(item.pop("prompt_file"))).resolve()
        item["prompt"] = prompt_path.read_text(encoding="utf-8")

    refs = item.get("refs", [])
    if not isinstance(refs, list):
        raise ValueError(f"{label}.refs must be a list")
    item["refs"] = [resolve_path(str(value), base) for value in refs]

    if item.get("image"):
        item["image"] = resolve_path(str(item["image"]), base)

    return item


def expand_batch(path: Path) -> list[dict[str, Any]]:
    data = load_yaml(path)
    jobs = data.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("batch YAML requires a non-empty jobs list")

    base = path.parent.resolve()
    expanded = []
    for index, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            raise ValueError(f"jobs[{index - 1}] must be an object")
        expanded.append(
            _expand_job(
                job,
                base=base,
                label=f"jobs[{index - 1}]",
            )
        )
    return expanded


def _merge_job(base: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    merged = {**base, **run}

    base_output = base.get("output")
    run_output = run.get("output")
    if isinstance(base_output, dict) and isinstance(run_output, dict):
        merged["output"] = {**base_output, **run_output}

    base_watermark = base.get("watermark")
    run_watermark = run.get("watermark")
    if isinstance(base_watermark, dict) and isinstance(run_watermark, dict):
        watermark = {**base_watermark, **run_watermark}
        base_metadata = base_watermark.get("aigc_metadata")
        run_metadata = run_watermark.get("aigc_metadata")
        if isinstance(base_metadata, dict) and isinstance(run_metadata, dict):
            watermark["aigc_metadata"] = {**base_metadata, **run_metadata}
        merged["watermark"] = watermark

    return merged


def expand_matrix(path: Path) -> list[dict[str, Any]]:
    data = load_yaml(path)
    common = data.get("base", {})
    runs = data.get("runs")
    default_variations = int(data.get("variations", 1))
    if not isinstance(common, dict):
        raise ValueError("matrix base must be an object")
    if not isinstance(runs, list) or not runs:
        raise ValueError("matrix YAML requires a non-empty runs list")

    base = path.parent.resolve()
    jobs = []
    for index, run in enumerate(runs, start=1):
        if not isinstance(run, dict):
            raise ValueError(f"runs[{index - 1}] must be an object")
        merged = _merge_job(common, run)
        merged.setdefault("variations", default_variations)
        jobs.append(
            _expand_job(
                merged,
                base=base,
                label=f"runs[{index - 1}]",
            )
        )
    return jobs


def audio_config_from_job(job: dict[str, Any]) -> AudioConfig:
    output = dict(job.get("output", {}))
    return AudioConfig(**output)


def watermark_from_job(job: dict[str, Any]) -> WatermarkConfig | None:
    value = job.get("watermark")
    if value in (None, False):
        return None
    if value is True:
        return WatermarkConfig(aigc_watermark=True)
    if isinstance(value, dict):
        return WatermarkConfig(**value)
    raise ValueError("watermark must be boolean or object")
