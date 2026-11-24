from __future__ import annotations

import re
import shutil
import sys
import textwrap
import threading
import time
import unicodedata
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .models import ReplayReference, SeedAudioRequest
from .runs import redact_urls_in_text

_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:byteplus_api_key|api[_-]?key|access[_-]?token|auth[_-]?token|"
    r"password|passwd|secret|client[_-]?secret)\b\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_BASE64_FIELD = re.compile(
    r"(?is)(\b(?:audio_data|image_data|base64|audio)\b\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[A-Za-z0-9+/]+=*)"
)
_BASE64_DATA_URL = re.compile(r"(?is)\bdata:[a-z0-9.+/-]+;base64,[A-Za-z0-9+/]+=*")
_LONG_BASE64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{160,}={0,2}(?![A-Za-z0-9+/])")


def safe_display_text(value: Any, *, preserve_newlines: bool = False) -> str:
    """Redact sensitive strings and neutralize terminal controls for display only."""
    text = redact_urls_in_text(str(value))
    text = _CREDENTIAL_ASSIGNMENT.sub(r"\1<redacted>", text)
    text = _BEARER_TOKEN.sub("Bearer <redacted>", text)
    text = _BASE64_FIELD.sub(r"\1<base64 omitted>", text)
    text = _BASE64_DATA_URL.sub("<base64 omitted>", text)
    text = _LONG_BASE64.sub("<base64 omitted>", text)

    safe: list[str] = []
    for char in text:
        if char == "\n" and preserve_newlines:
            safe.append(char)
        elif unicodedata.category(char) in {"Cc", "Cf", "Cs"}:
            safe.append("␛" if char == "\x1b" else "�")
        else:
            safe.append(char)
    return "".join(safe)


def safe_error_message(error: BaseException) -> str:
    return safe_display_text(error, preserve_newlines=False).replace("\n", " ")


def _seconds(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return f"{value:.1f}s"


def _duration(value: Any) -> str | None:
    return _seconds(value)


def _file_size(value: int | None) -> str | None:
    if value is None:
        return None
    if value >= 1000:
        return f"{value / 1000:.1f} KB"
    return f"{value} B"


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _clock_label(seconds: float) -> str:
    whole = max(0, int(seconds))
    hours, remainder = divmod(whole, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"
    return f"{minutes:02d}:{seconds_part:02d}"


class ExecutionReporter:
    """Chronological terminal output for one CLI execution."""

    def __init__(
        self,
        *,
        command: str,
        dry_run: bool,
        as_json: bool,
        writer: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wait_interval: float = 1.0,
        wait_fn: Callable[[threading.Event, float], bool] | None = None,
        terminal_width: int | None = None,
    ) -> None:
        self.command = command
        self.dry_run = dry_run
        self.as_json = as_json
        self._clock = clock
        self._wait_interval = wait_interval
        self._wait_fn = wait_fn or (lambda stop, interval: stop.wait(interval))
        self._terminal_width = terminal_width or shutil.get_terminal_size((80, 24)).columns
        self._writer = writer or self._write_to_terminal
        self._write_lock = threading.Lock()
        self._execution_started_at = clock()
        self._generation_started_at: float | None = None
        self._request_started_at: float | None = None
        self._wait_stop: threading.Event | None = None
        self._wait_thread: threading.Thread | None = None
        self._wait_lock = threading.Lock()
        self._request_elapsed: float | None = None
        self._provider_log_id: str | None = None
        self._stage = "command setup"
        self._active = False
        self._failure_reported = False
        self._closed = False
        self._planned_generations: int | None = None
        self._generation_count = 0
        self._prepared_count = 0
        self._failed_count = 0
        self._outputs: list[dict[str, Any]] = []
        self._current_name: str | None = None
        self._current_run_dir: Path | None = None
        self._root: Path | None = None

    @property
    def planned_generations(self) -> int | None:
        return self._planned_generations

    def _write_to_terminal(self, line: str) -> None:
        stream = sys.stderr if self.as_json else sys.stdout
        print(line, file=stream, flush=True)

    def _write(self, line: str) -> None:
        with self._write_lock:
            self._writer(line)

    def _elapsed(self) -> float:
        return max(0.0, self._clock() - self._execution_started_at)

    def event(self, message: str) -> None:
        safe = safe_display_text(message).replace("\n", " ")
        self._write(f"[{_clock_label(self._elapsed())}] {safe}")

    def start(self) -> None:
        self._write(f"SEED AUDIO / {safe_display_text(self.command).upper()}")

    def configure_plan(
        self,
        *,
        workflow: str | Path | None = None,
        jobs: int | None = None,
        generations: int | None = None,
        runs_root: Path | None = None,
        workflow_loaded: bool = False,
    ) -> None:
        self._planned_generations = generations
        self._root = runs_root
        if workflow is not None:
            self._write(f"Workflow      {safe_display_text(workflow)}")
        if jobs is not None:
            self._write(f"Jobs          {jobs}")
        self._write(
            "Generations   "
            + (str(generations) if generations is not None else "undetermined")
        )
        self._write(f"Mode          {'dry-run' if self.dry_run else 'generation'}")
        self._write("")
        if workflow_loaded:
            self.event("Workflow loaded")
        self.event("Execution started")

    def set_stage(self, stage: str) -> None:
        self._stage = stage

    def begin_generation(
        self,
        *,
        position: int,
        total: int | None,
        name: str,
        variation: tuple[int, int] | None = None,
    ) -> None:
        self._active = True
        self._failure_reported = False
        self._current_name = name
        self._current_run_dir = None
        self._generation_started_at = self._clock()
        self._request_elapsed = None
        total_text = str(total) if total is not None else "?"
        self._write("")
        self._write(f"[{position:02d}/{total_text}] {safe_display_text(name)}")
        self.set_stage("input preparation")

    def set_run_dir(self, run_dir: Path) -> None:
        self._current_run_dir = run_dir

    def show_inputs(
        self,
        *,
        request: SeedAudioRequest,
        references: Sequence[ReplayReference],
        source_labels: Sequence[str] | None = None,
        variation: tuple[int, int] | None = None,
    ) -> None:
        payload = request.provider_payload()
        self._write("\nINPUTS")
        self._row("Model", request.model)
        if variation is not None:
            self._row("Variation", f"{variation[0]}/{variation[1]}")

        self._write("\n  Text prompt")
        prompt = safe_display_text(request.text_prompt, preserve_newlines=True)
        indent = "    "
        width = max(40, self._terminal_width - len(indent))
        for line in prompt.split("\n"):
            if not line:
                self._write("")
                continue
            wrapped = textwrap.wrap(
                line,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
                drop_whitespace=True,
            ) or [""]
            for part in wrapped:
                self._write(f"{indent}{part}")

        self._write("\n  References")
        if not references:
            self._write("    None")
        else:
            audio_position = 0
            for index, reference in enumerate(references, start=1):
                if reference.kind == "audio":
                    audio_position += 1
                    label = f"@Audio{audio_position}"
                else:
                    label = f"Image {index}"
                source = (
                    source_labels[index - 1]
                    if source_labels is not None and index <= len(source_labels)
                    else reference.source
                )
                safe_source = safe_display_text(source)
                if reference.is_url:
                    self._write(f"    {label:<12} {reference.kind} | {safe_source}")
                    continue
                self._write(f"    {label:<12} {safe_source}")
                details = [reference.kind]
                suffix = Path(str(source)).suffix.lower().lstrip(".")
                if suffix:
                    details.append(suffix.upper())
                size = _file_size(reference.bytes)
                if size is not None:
                    details.append(size)
                duration = _duration(reference.duration_seconds)
                if duration is not None:
                    details.append(duration)
                if details:
                    self._write(f"    {'':<12} {' | '.join(details)}")

        self._write("\n  Audio configuration")
        audio_config = payload.get("audio_config", {})
        config_items = (
            ("format", "Format", ""),
            ("sample_rate", "Sample rate", " Hz"),
            ("speech_rate", "Speech rate", ""),
            ("loudness_rate", "Loudness rate", ""),
            ("pitch_rate", "Pitch rate", ""),
            ("enable_subtitle", "Enable subtitle", ""),
        )
        for key, label, suffix in config_items:
            if key in audio_config:
                value = f"{_format_value(audio_config[key])}{suffix}"
            else:
                value = "omitted (provider default)"
            self._row(label, value)
        watermark = payload.get("watermark")
        if watermark is not None:
            self._row(
                "Watermark",
                _format_value(watermark.get("aigc_watermark", "unavailable")),
            )

    def _row(self, label: str, value: Any) -> None:
        rendered = safe_display_text(value).replace("\n", " ")
        self._write(f"  {label:<14} {rendered}")

    def references_encoded(self, references: Sequence[ReplayReference]) -> None:
        audio_position = 0
        for index, reference in enumerate(references, start=1):
            if reference.is_url:
                continue
            if reference.kind == "audio":
                audio_position += 1
                label = f"@Audio{audio_position}"
            else:
                label = f"Image {index}"
            self.event(f"Reference encoded: {label} ({reference.kind})")

    def input_validated(self, *, replay: bool = False) -> None:
        self.set_stage("provider request")
        message = (
            "Replay inputs reconstructed and validated"
            if replay
            else "Input validated"
        )
        self.event(message)

    def dry_run_prepared(self) -> None:
        self.event("Dry-run plan prepared; no provider call was made")
        self._prepared_count += 1
        self._active = False

    def request_started(self, request_id: str | None = None) -> None:
        with self._wait_lock:
            if self._request_started_at is not None:
                return
            self._request_started_at = self._clock()
            self._wait_stop = threading.Event()
            suffix = f" (request ID {safe_display_text(request_id)})" if request_id else ""
            self.event(f"API request started{suffix}")
            stop = self._wait_stop
            self._wait_thread = threading.Thread(
                target=self._wait_loop,
                args=(stop,),
                name="seed-audio-reporting-wait",
                daemon=True,
            )
            self._wait_thread.start()

    def _wait_loop(self, stop: threading.Event) -> None:
        while not self._wait_fn(stop, self._wait_interval):
            with self._wait_lock:
                if stop.is_set() or self._request_started_at is None:
                    return
                elapsed = max(0.0, self._clock() - self._request_started_at)
            self.event(f"Awaiting API response... {elapsed:.1f}s")

    def _stop_waiting(self) -> float | None:
        with self._wait_lock:
            started = self._request_started_at
            stop = self._wait_stop
            thread = self._wait_thread
            self._request_started_at = None
            self._wait_stop = None
            self._wait_thread = None
        elapsed = max(0.0, self._clock() - started) if started is not None else None
        if stop is not None:
            stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join()
        return elapsed

    def provider_response_received(self, provider_log_id: str | None = None) -> float:
        elapsed = self._stop_waiting() or 0.0
        self._request_elapsed = elapsed
        self._provider_log_id = provider_log_id
        self.set_stage("provider response handling")
        self.event(f"API response received ({elapsed:.1f}s)")
        if provider_log_id:
            self.event(f"Provider log ID: {provider_log_id}")
        return elapsed

    def persisting(self) -> None:
        self.set_stage("artifact persistence")
        self.event("Persisting run artifacts")

    def generation_succeeded(
        self,
        *,
        manifest: dict[str, Any],
        run_dir: Path,
        name: str,
        external_out: Path | None = None,
    ) -> None:
        self._stop_waiting()
        generation_started_at = self._generation_started_at
        elapsed = (
            max(0.0, self._clock() - generation_started_at)
            if generation_started_at is not None
            else 0.0
        )
        self.event("Audio and metadata saved")
        self._write("\nOUTPUT")
        self._row("Status", "completed")
        if self._request_elapsed is not None:
            self._row("API elapsed", f"{self._request_elapsed:.1f}s")
        self._row("Generation elapsed", f"{elapsed:.1f}s")
        duration = _duration(manifest.get("duration_seconds"))
        if duration is not None:
            self._row("Audio duration", duration)
        billable = _duration(manifest.get("billing_duration_seconds"))
        if billable is not None:
            self._row("Billable audio", billable)

        safe_run_dir = safe_display_text(run_dir)
        self._row("Run folder", safe_run_dir)
        artifacts = manifest.get("artifacts", {})
        for key, label in (
            ("audio", "Audio"),
            ("recipe", "Recipe"),
            ("request", "Request"),
            ("response", "Response"),
            ("prompt", "Prompt file"),
            ("subtitles", "Subtitles"),
        ):
            filename = artifacts.get(key)
            if filename:
                self._row(label, Path(safe_run_dir) / str(filename))
        self._row("Manifest", Path(safe_run_dir) / "manifest.json")
        for reference in manifest.get("references", []):
            if not reference.get("is_url") and reference.get("source"):
                self._row(
                    "Reference copy",
                    Path(safe_run_dir) / str(reference["source"]),
                )
        if external_out is not None:
            self._row("Additional copy", external_out)
        if manifest.get("request_id"):
            self._row("Request ID", manifest["request_id"])
        if manifest.get("provider_log_id"):
            self._row("Provider log ID", manifest["provider_log_id"])

        self._outputs.append(
            {
                "name": name,
                "audio": str(run_dir / artifacts["audio"]),
                "duration": manifest.get("duration_seconds"),
                "billable": manifest.get("billing_duration_seconds"),
            }
        )
        self._generation_count += 1
        self._active = False
        self._current_run_dir = None

    def _sum_available(self, key: str) -> tuple[float, int]:
        values = [item[key] for item in self._outputs]
        valid = [
            value
            for value in values
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        return sum(valid), len(valid)

    def _summary_outputs(self) -> None:
        if not self._outputs:
            return
        self._write("\nOUTPUTS")
        for item in self._outputs:
            name = safe_display_text(Path(item["audio"]).name)
            duration = _duration(item["duration"])
            suffix = f"  {duration}" if duration is not None else ""
            self._write(f"  {name}{suffix}")

    def finish_success(self) -> None:
        self._stop_waiting()
        self.event("Execution finished")
        self._write("")
        if self.dry_run:
            self._write(f"{self.command.upper()} DRY RUN PREPARED")
            self._row("Generations prepared", self._prepared_count)
            self._row("Provider calls", 0)
        else:
            self._write(f"{self.command.upper()} COMPLETED")
            total = self._planned_generations
            completed = self._generation_count
            self._row(
                "Generations",
                f"{completed}/{total}" if total is not None else str(completed),
            )
            self._row("Failed", 0)
            self._row("Elapsed", f"{self._elapsed():.1f}s")
            self._render_totals("duration", "Audio produced")
            self._render_totals("billable", "Billable audio")
            self._summary_outputs()
            if self._root is not None:
                self._write(f"\nArtifacts root: {safe_display_text(self._root)}")
        if self.dry_run:
            self._row("Elapsed", f"{self._elapsed():.1f}s")

    def _render_totals(self, key: str, label: str) -> None:
        total, available = self._sum_available(key)
        if available == 0:
            return
        completed = len(self._outputs)
        qualifier = "" if available == completed else " (partial)"
        self._row(label + qualifier, f"{total:.1f}s")

    def execution_failed(self, error: BaseException) -> None:
        wait_elapsed = self._stop_waiting()
        message = safe_error_message(error)
        if self._active and not self._failure_reported:
            detail = f"Generation failed during {self._stage}"
            if wait_elapsed is not None:
                detail += f" (API elapsed {wait_elapsed:.1f}s)"
            self.event(f"{detail}: {message}")
            self._failed_count += 1
            self._active = False
            self._failure_reported = True
        else:
            self.event(f"Execution failed during {self._stage}: {message}")
        self.event("Execution stopped")
        self._write("")
        self._write(f"{self.command.upper()} FAILED")
        total = self._planned_generations
        completed = self._generation_count
        if total is not None:
            self._row("Generations completed", f"{completed}/{total}")
            self._row("Failed", self._failed_count)
            self._row("Not executed", max(0, total - completed - self._failed_count))
        else:
            self._row("Generations completed", completed)
            self._row("Failed", self._failed_count)
            self._row("Not executed", "undetermined")
        self._row("Elapsed", f"{self._elapsed():.1f}s")
        self._summary_outputs()
        if self._current_run_dir is not None and self._current_run_dir.exists():
            self._row("Incomplete run folder", self._current_run_dir)
        if self._root is not None:
            self._write(f"\nArtifacts root: {safe_display_text(self._root)}")

    def execution_interrupted(self) -> None:
        self._stop_waiting()
        if self._active:
            self._failed_count += 1
            self.event(f"Generation interrupted during {self._stage}")
            self._active = False
        else:
            self.event("Execution interrupted")
        self.event("Execution stopped")
        self._write("")
        self._write(f"{self.command.upper()} INTERRUPTED")
        self._row("Generations completed", self._generation_count)
        self._row("Failed or interrupted", self._failed_count)
        if self._planned_generations is not None:
            self._row(
                "Not executed",
                max(0, self._planned_generations - self._generation_count - self._failed_count),
            )
        self._summary_outputs()
        if self._root is not None:
            self._write(f"\nArtifacts root: {safe_display_text(self._root)}")

    def close(self) -> None:
        if self._closed:
            return
        self._stop_waiting()
        self._closed = True


def planned_generation_count(jobs: Sequence[dict[str, Any]]) -> int | None:
    """Count a workflow's plan without moving per-job validation earlier."""
    total = 0
    for job in jobs:
        try:
            count = int(job.get("variations", 1))
        except (TypeError, ValueError, OverflowError):
            return None
        if not 1 <= count <= 5:
            return None
        total += count
    return total
