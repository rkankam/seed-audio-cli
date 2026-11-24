from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated

import typer

from .client import BytePlusClient
from .config import api_key
from .models import AudioConfig, ReplayRecipe, WatermarkConfig
from .runs import (
    build_request_from_recipe,
    make_run_dir,
    persist_result,
    prepare_recipe,
    redact_provider_payload,
    redact_sensitive_values,
)
from .workflows import (
    audio_config_from_job,
    expand_batch,
    expand_matrix,
    watermark_from_job,
)

app = typer.Typer(
    no_args_is_help=True,
    help="Reproducible CLI for the official BytePlus Seed Audio 1.0 API.",
)

RUNS_ROOT = Path("runs")


def _read_prompt(prompt: str | None, prompt_file: Path | None) -> str:
    if bool(prompt) == bool(prompt_file):
        raise ValueError("provide exactly one of --prompt or --prompt-file")
    if prompt_file:
        return prompt_file.read_text(encoding="utf-8")
    assert prompt is not None
    return prompt


def _emit(value: dict, as_json: bool) -> None:
    safe_value = redact_sensitive_values(value)
    if as_json:
        typer.echo(json.dumps(safe_value, ensure_ascii=False, sort_keys=True))
    else:
        typer.echo(json.dumps(safe_value, ensure_ascii=False, indent=2))


def _validate_out_path(out: Path | None, audio_format: str) -> None:
    if out is None:
        return
    expected = {
        "wav": {".wav"},
        "mp3": {".mp3"},
        "pcm": {".pcm"},
        "ogg_opus": {".ogg", ".opus"},
    }[audio_format]
    if out.suffix.lower() not in expected:
        allowed = ", ".join(sorted(expected))
        raise ValueError(
            f"--out extension must match --format {audio_format}; expected {allowed}"
        )


def _generate_once(
    *,
    prompt: str,
    refs: list[str],
    image: str | None,
    model: str,
    config: AudioConfig,
    watermark: WatermarkConfig | None,
    name: str,
    runs_root: Path,
    out: Path | None,
    dry_run: bool,
    artifact_prefix: str | None = None,
) -> dict:
    _validate_out_path(out, config.format)

    if dry_run:
        recipe = prepare_recipe(
            model=model,
            prompt=prompt,
            audio_refs=refs,
            image_ref=image,
            audio_config=config,
            watermark=watermark,
            run_dir=None,
        )
        request, _ = build_request_from_recipe(recipe, Path.cwd())
        return {
            "ok": True,
            "dry_run": True,
            "request": redact_provider_payload(request.provider_payload()),
        }

    run_dir = make_run_dir(runs_root, name)
    try:
        recipe = prepare_recipe(
            model=model,
            prompt=prompt,
            audio_refs=refs,
            image_ref=image,
            audio_config=config,
            watermark=watermark,
            run_dir=run_dir,
        )
        request, normalized_refs = build_request_from_recipe(recipe, run_dir)
        recipe = recipe.model_copy(update={"references": normalized_refs})

        client = BytePlusClient(api_key(required=True) or "")
        result = client.create(request.provider_payload())
    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise

    manifest = persist_result(
        run_dir=run_dir,
        recipe=recipe,
        request=request,
        provider_result=result,
        command="gen",
        external_out=out,
        artifact_prefix=artifact_prefix,
    )
    return {
        "ok": True,
        "run_id": manifest["run_id"],
        "run_dir": str(run_dir),
        "audio": str(run_dir / manifest["artifacts"]["audio"]),
        "manifest": str(run_dir / "manifest.json"),
        "duration_seconds": manifest["duration_seconds"],
        "billing_duration_seconds": manifest["billing_duration_seconds"],
        "request_id": manifest["request_id"],
        "provider_log_id": manifest["provider_log_id"],
    }


@app.command()
def gen(
    prompt: Annotated[str | None, typer.Option("--prompt")] = None,
    prompt_file: Annotated[Path | None, typer.Option("--prompt-file")] = None,
    ref: Annotated[list[str] | None, typer.Option("--ref")] = None,
    image: Annotated[str | None, typer.Option("--image")] = None,
    model: Annotated[str, typer.Option("--model")] = "seed-audio-1.0",
    format: Annotated[str, typer.Option("--format")] = "wav",
    sample_rate: Annotated[int | None, typer.Option("--sample-rate")] = None,
    speech_rate: Annotated[int, typer.Option("--speech-rate")] = 0,
    loudness_rate: Annotated[int, typer.Option("--loudness-rate")] = 0,
    pitch_rate: Annotated[int, typer.Option("--pitch-rate")] = 0,
    subtitles: Annotated[bool, typer.Option("--subtitles")] = False,
    aigc_watermark: Annotated[bool, typer.Option("--aigc-watermark")] = False,
    variations: Annotated[int, typer.Option("-n", "--variations", min=1, max=5)] = 1,
    name: Annotated[str, typer.Option("--name")] = "run",
    runs_root: Annotated[Path, typer.Option("--runs-root")] = RUNS_ROOT,
    out: Annotated[Path | None, typer.Option("--out")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        text = _read_prompt(prompt, prompt_file)
        config = AudioConfig(
            format=format,
            sample_rate=sample_rate,
            speech_rate=speech_rate,
            loudness_rate=loudness_rate,
            pitch_rate=pitch_rate,
            enable_subtitle=subtitles,
        )
        watermark = (
            WatermarkConfig(aigc_watermark=True) if aigc_watermark else None
        )

        results = []
        for index in range(1, variations + 1):
            variant_name = name if variations == 1 else f"{name}-{index:02d}"
            variant_out = out
            if out is not None and variations > 1:
                variant_out = out.with_name(
                    f"{out.stem}_{index:02d}{out.suffix}"
                )
            results.append(
                _generate_once(
                    prompt=text,
                    refs=ref or [],
                    image=image,
                    model=model,
                    config=config,
                    watermark=watermark,
                    name=variant_name,
                    runs_root=runs_root,
                    out=variant_out,
                    dry_run=dry_run,
                    artifact_prefix=None,
                )
            )
        _emit({"ok": True, "runs": results}, as_json)
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)}, as_json)
        raise typer.Exit(code=2) from exc


@app.command()
def replay(
    run_dir: Path,
    runs_root: Annotated[Path, typer.Option("--runs-root")] = RUNS_ROOT,
    name: Annotated[str | None, typer.Option("--name")] = None,
    out: Annotated[Path | None, typer.Option("--out")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        source = run_dir.resolve()
        recipe = ReplayRecipe.model_validate_json(
            (source / "recipe.json").read_text(encoding="utf-8")
        )
        request, _ = build_request_from_recipe(recipe, source, replay=True)
        _validate_out_path(out, recipe.audio_config.format)

        if dry_run:
            _emit(
                {
                    "ok": True,
                    "dry_run": True,
                    "request": redact_provider_payload(request.provider_payload()),
                },
                as_json,
            )
            return

        target = make_run_dir(runs_root, name or f"replay-{source.name}")
        try:
            replay_recipe = prepare_recipe(
                model=recipe.model,
                prompt=recipe.text_prompt,
                audio_refs=[
                    str(source / item.source) if not item.is_url else item.source
                    for item in recipe.references
                    if item.kind == "audio"
                ],
                image_ref=next(
                    (
                        str(source / item.source)
                        if not item.is_url
                        else item.source
                        for item in recipe.references
                        if item.kind == "image"
                    ),
                    None,
                ),
                audio_config=recipe.audio_config,
                watermark=recipe.watermark,
                run_dir=target,
            )
            request, normalized = build_request_from_recipe(
                replay_recipe, target, replay=True
            )
            replay_recipe = replay_recipe.model_copy(
                update={"references": normalized}
            )

            result = BytePlusClient(api_key(required=True) or "").create(
                request.provider_payload()
            )
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

        manifest = persist_result(
            run_dir=target,
            recipe=replay_recipe,
            request=request,
            provider_result=result,
            command=f"replay:{source.name}",
            external_out=out,
        )
        _emit(
            {
                "ok": True,
                "run_id": manifest["run_id"],
                "run_dir": str(target),
                "audio": str(target / manifest["artifacts"]["audio"]),
                "manifest": str(target / "manifest.json"),
            },
            as_json,
        )
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)}, as_json)
        raise typer.Exit(code=2) from exc


def _run_workflow(
    jobs: list[dict],
    *,
    runs_root: Path,
    dry_run: bool,
) -> list[dict]:
    results = []
    for job_index, job in enumerate(jobs, start=1):
        prompt = job.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError(f"job {job_index} requires prompt or prompt_file")

        variations = int(job.get("variations", 1))
        if not 1 <= variations <= 5:
            raise ValueError(f"job {job_index} variations must be between 1 and 5")

        for variant in range(1, variations + 1):
            base_name = str(job.get("id", f"job-{job_index:02d}"))
            name = (
                base_name
                if variations == 1
                else f"{base_name}-{variant:02d}"
            )
            results.append(
                _generate_once(
                    prompt=prompt,
                    refs=list(job.get("refs", [])),
                    image=job.get("image"),
                    model=str(job.get("model", "seed-audio-1.0")),
                    config=audio_config_from_job(job),
                    watermark=watermark_from_job(job),
                    name=name,
                    runs_root=runs_root,
                    out=None,
                    dry_run=dry_run,
                    artifact_prefix=name,
                )
            )
    return results


@app.command()
def batch(
    workflow: Path,
    runs_root: Annotated[Path, typer.Option("--runs-root")] = RUNS_ROOT,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        results = _run_workflow(
            expand_batch(workflow.resolve()),
            runs_root=runs_root,
            dry_run=dry_run,
        )
        _emit({"ok": True, "runs": results}, as_json)
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)}, as_json)
        raise typer.Exit(code=2) from exc


@app.command()
def matrix(
    workflow: Path,
    runs_root: Annotated[Path, typer.Option("--runs-root")] = RUNS_ROOT,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        results = _run_workflow(
            expand_matrix(workflow.resolve()),
            runs_root=runs_root,
            dry_run=dry_run,
        )
        _emit({"ok": True, "runs": results}, as_json)
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)}, as_json)
        raise typer.Exit(code=2) from exc


if __name__ == "__main__":
    app()
