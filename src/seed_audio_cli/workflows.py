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
        item = dict(job)
        if item.get("prompt_file"):
            prompt_path = (base / item.pop("prompt_file")).resolve()
            item["prompt"] = prompt_path.read_text(encoding="utf-8")
        item["refs"] = [resolve_path(value, base) for value in item.get("refs", [])]
        if item.get("image"):
            item["image"] = resolve_path(item["image"], base)
        expanded.append(item)
    return expanded


def expand_matrix(path: Path) -> list[dict[str, Any]]:
    data = load_yaml(path)
    common = data.get("base", {})
    runs = data.get("runs")
    default_variations = int(data.get("variations", 1))
    if not isinstance(common, dict):
        raise ValueError("matrix base must be an object")
    if not isinstance(runs, list) or not runs:
        raise ValueError("matrix YAML requires a non-empty runs list")

    jobs = []
    for index, run in enumerate(runs, start=1):
        if not isinstance(run, dict):
            raise ValueError(f"runs[{index - 1}] must be an object")
        merged = {**common, **run}
        merged.setdefault("variations", default_variations)
        jobs.append(merged)

    synthetic = {"jobs": jobs}
    temp = path.parent / f".{path.name}.expanded.tmp.yaml"
    try:
        temp.write_text(yaml.safe_dump(synthetic, sort_keys=False), encoding="utf-8")
        return expand_batch(temp)
    finally:
        temp.unlink(missing_ok=True)


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
