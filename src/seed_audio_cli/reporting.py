from __future__ import annotations

import os
import re
import shutil
import sys
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
_ANSI_SEQUENCE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)

LABEL_WIDTH = 22
ROW_INDENT = 2
ROW_GAP = 1
PROMPT_INDENT = 4
COUNTER_DIGITS = 2
COLOR_CODES = {
    "title": "1;36",
    "section": "1;36",
    "generation": "1;36",
    "success": "32",
    "wait": "33",
    "error": "31",
    "secondary": "90",
}
_FORMAT_CONTROLS = {
    "\u061c",
    "\u200e",
    "\u200f",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
}


def _is_variation_selector(char: str) -> bool:
    codepoint = ord(char)
    return 0xFE00 <= codepoint <= 0xFE0F or 0xE0100 <= codepoint <= 0xE01EF


def _is_regional_indicator(char: str) -> bool:
    return 0x1F1E6 <= ord(char) <= 0x1F1FF


def _grapheme_clusters(text: str) -> list[str]:
    """Group combining marks and common emoji sequences for terminal wrapping."""
    clusters: list[str] = []
    regional_count = 0
    for char in text:
        if not clusters:
            clusters.append(char)
            regional_count = int(_is_regional_indicator(char))
            continue
        previous = clusters[-1]
        joins_previous = (
            unicodedata.combining(char) != 0
            or _is_variation_selector(char)
            or 0x1F3FB <= ord(char) <= 0x1F3FF
            or char == "\u20e3"
            or char == "\u200d"
            or previous.endswith("\u200d")
            or (_is_regional_indicator(char) and regional_count == 1)
        )
        if joins_previous:
            clusters[-1] += char
        else:
            clusters.append(char)
        regional_count = regional_count + 1 if _is_regional_indicator(char) else 0
    return clusters


def visible_width(text: str) -> int:
    """Return terminal cell width, ignoring ANSI sequences and combining marks."""
    plain = _ANSI_SEQUENCE.sub("", text)
    width = 0
    for cluster in _grapheme_clusters(plain):
        if "\u200d" in cluster or "\u20e3" in cluster or sum(
            _is_regional_indicator(char) for char in cluster
        ) == 2:
            width += max(
                (
                    2
                    if unicodedata.east_asian_width(char) in {"W", "F"}
                    else 1
                    for char in cluster
                    if not unicodedata.combining(char)
                    and not _is_variation_selector(char)
                    and char != "\u200d"
                    and unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
                ),
                default=0,
            )
            continue
        width += sum(
            0
            if unicodedata.combining(char)
            or _is_variation_selector(char)
            or unicodedata.category(char) in {"Cc", "Cf", "Cs"}
            else 2
            if unicodedata.east_asian_width(char) in {"W", "F"}
            else 1
            for char in cluster
        )
    return width


def _split_long_token(token: str, width: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    current_width = 0
    for cluster in _grapheme_clusters(token):
        cluster_width = visible_width(cluster)
        if current and current_width + cluster_width > width:
            pieces.append(current)
            current = ""
            current_width = 0
        current += cluster
        current_width += cluster_width
    if current or not pieces:
        pieces.append(current)
    return pieces


def wrap_visible(text: str, width: int) -> list[str]:
    """Wrap one logical line while retaining words and in-line whitespace."""
    width = max(1, width)
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    pending_space = ""
    for token in re.findall(r"\s+|\S+", text):
        if token.isspace():
            pending_space += token
            continue
        pieces = _split_long_token(token, width)
        for piece_index, piece in enumerate(pieces):
            separator = pending_space if current or not lines else ""
            candidate = f"{current}{separator}{piece}"
            if current and visible_width(candidate) > width:
                lines.append(current.rstrip())
                current = piece
            else:
                current = candidate
            pending_space = ""
            if piece_index < len(pieces) - 1:
                lines.append(current)
                current = ""
    if pending_space:
        pieces = _split_long_token(pending_space, width)
        for piece in pieces:
            candidate = f"{current}{piece}"
            if current and visible_width(candidate) > width:
                lines.append(current.rstrip())
                current = piece
            else:
                current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def generation_counter(position: int, total: int | None) -> str:
    total_text = str(total) if total is not None else "?"
    digits = max(COUNTER_DIGITS, len(total_text))
    denominator = total_text.zfill(digits) if total is not None else "?" * digits
    return f"[{position:0{digits}d}/{denominator}]"


def _terminal_columns(stream: Any) -> int:
    try:
        columns = os.get_terminal_size(stream.fileno()).columns
    except (AttributeError, OSError, ValueError):
        try:
            columns = shutil.get_terminal_size((80, 24)).columns
        except OSError:
            columns = 80
    return max(1, columns)


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
        elif char in {"\u200c", "\u200d"}:
            safe.append(char)
        elif char in _FORMAT_CONTROLS or unicodedata.category(char) in {"Cc", "Cf", "Cs"}:
            safe.append("␛" if char == "\x1b" else "�")
        else:
            safe.append(char)
    return "".join(safe)


def safe_json_text(value: Any, *, redact_long_base64: bool = True) -> str:
    """Redact secret-like JSON text without applying human display cleanup.

    Structured reference payloads redact their Base64 fields before emission.
    Avoid the broad ``audio=...`` display matcher here: it can rewrite valid
    prompt text and filesystem paths. The JSON encoder safely escapes controls.
    """
    text = redact_urls_in_text(str(value))
    text = _CREDENTIAL_ASSIGNMENT.sub(r"\1<redacted>", text)
    text = _BEARER_TOKEN.sub("Bearer <redacted>", text)
    text = _BASE64_DATA_URL.sub("<base64 omitted>", text)
    if redact_long_base64:
        text = _LONG_BASE64.sub("<base64 omitted>", text)
    return text


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
        color_enabled: bool | None = None,
    ) -> None:
        self.command = command
        self.dry_run = dry_run
        self.as_json = as_json
        self._clock = clock
        self._wait_interval = wait_interval
        self._wait_fn = wait_fn or (lambda stop, interval: stop.wait(interval))
        self._terminal_width_override = terminal_width
        self._stream = sys.stderr if as_json else sys.stdout
        no_color = bool(os.environ.get("NO_COLOR"))
        try:
            stream_is_tty = bool(self._stream.isatty())
        except (AttributeError, OSError):
            stream_is_tty = False
        term_supports_color = os.environ.get("TERM") != "dumb"
        if color_enabled is None:
            self._color_enabled = stream_is_tty and term_supports_color and not no_color
        else:
            self._color_enabled = color_enabled and not no_color
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

    def _columns(self) -> int:
        if self._terminal_width_override is not None:
            return max(1, self._terminal_width_override)
        return _terminal_columns(self._stream)

    def _paint(self, text: str, style: str) -> str:
        if not self._color_enabled:
            return text
        code = COLOR_CODES[style]
        return f"\x1b[{code}m{text}\x1b[0m"

    def _section(self, title: str) -> None:
        self._write(self._paint(title, "section"))

    def _wrapped(self, text: str, *, indent: int, style: str | None = None) -> None:
        width = max(1, self._columns() - indent)
        for line in wrap_visible(text, width):
            rendered = self._paint(line, style) if style else line
            self._write(f"{' ' * indent}{rendered}")

    @property
    def planned_generations(self) -> int | None:
        return self._planned_generations

    def _write_to_terminal(self, line: str) -> None:
        stream = sys.stderr if self.as_json else sys.stdout
        print(line, file=stream, flush=True)

    def _write(self, line: str) -> None:
        self._write_lines([line])

    def _write_lines(self, lines: Sequence[str]) -> None:
        with self._write_lock:
            for line in lines:
                self._writer(line)

    def _elapsed(self) -> float:
        return max(0.0, self._clock() - self._execution_started_at)

    def event(self, message: str) -> None:
        safe = safe_display_text(message).replace("\n", " ")
        lowered = safe.casefold()
        style: str | None = None
        if "awaiting api response" in lowered:
            style = "wait"
        elif any(token in lowered for token in ("failed", "error", "interrupted")):
            style = "error"
        elif any(
            token in lowered
            for token in (
                "validated",
                "saved",
                "received",
                "finished",
                "loaded",
                "prepared",
            )
        ):
            style = "success"
        timestamp_text = f"[{_clock_label(self._elapsed())}]"
        timestamp = self._paint(timestamp_text, "secondary")
        prefix_width = visible_width(timestamp_text) + 1
        message_width = max(1, self._columns() - prefix_width)
        parts = wrap_visible(safe, message_width)
        rendered_parts = [
            self._paint(part, style) if style is not None else part for part in parts
        ]
        self._write_lines(
            [f"{timestamp} {rendered_parts[0]}"]
            + [f"{' ' * prefix_width}{part}" for part in rendered_parts[1:]]
        )

    def start(self) -> None:
        self._write(
            self._paint(
                f"SEED AUDIO / {safe_display_text(self.command).upper()}", "title"
            )
        )

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
            self._row("Workflow", workflow)
        if jobs is not None:
            self._row("Jobs", jobs)
        self._row("Generations", generations if generations is not None else "undetermined")
        self._row("Mode", "dry-run" if self.dry_run else "generation")
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
        self._write("")
        identifier = f"{generation_counter(position, total)} {safe_display_text(name)}"
        for line in wrap_visible(identifier, self._columns()):
            self._write(self._paint(line, "generation"))
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
        self._write("")
        self._section("INPUTS")
        self._row("Model", request.model)
        if variation is not None:
            self._row("Variation", f"{variation[0]}/{variation[1]}")

        self._write("")
        self._write(self._paint("  Text prompt", "secondary"))
        prompt = safe_display_text(request.text_prompt, preserve_newlines=True)
        indent = PROMPT_INDENT
        width = max(1, self._columns() - indent)
        for line in prompt.split("\n"):
            if not line:
                self._write("")
                continue
            for part in wrap_visible(line, width):
                self._write(f"{' ' * indent}{part}")

        self._write("")
        self._write(self._paint("  References", "secondary"))
        if not references:
            self._wrapped("None", indent=PROMPT_INDENT)
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
                    self._reference_row(label, f"{reference.kind} | {safe_source}")
                    continue
                self._reference_row(label, safe_source)
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
                    self._reference_row("", " | ".join(details))

        self._write("")
        self._write(self._paint("  Audio configuration", "secondary"))
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
            metadata = watermark.get("aigc_metadata")
            if isinstance(metadata, dict):
                if "enable" in metadata:
                    self._row("Implicit watermark", _format_value(metadata["enable"]))
                metadata_items = (
                    ("content_producer", "Content producer"),
                    ("produce_id", "Produce ID"),
                    ("content_propagator", "Content propagator"),
                    ("propagate_id", "Propagate ID"),
                )
                for key, label in metadata_items:
                    if key in metadata:
                        self._row(label, _format_value(metadata[key]))

    def _row(
        self, label: str, value: Any, *, value_style: str | None = None
    ) -> None:
        rendered = safe_display_text(value).replace("\n", " ")
        safe_label = safe_display_text(label).replace("\n", " ")
        label_prefix = " " * ROW_INDENT
        value_gap = " " * ROW_GAP
        available = self._columns()
        if available > ROW_INDENT + LABEL_WIDTH + ROW_GAP:
            value_indent = ROW_INDENT + LABEL_WIDTH + ROW_GAP
            value_width = max(1, available - value_indent)
            label_lines = wrap_visible(safe_label, LABEL_WIDTH)
            lines = wrap_visible(rendered, value_width)
            if len(label_lines) > 1:
                for line in label_lines:
                    self._write(self._paint(f"{label_prefix}{line}", "secondary"))
                first_value = (
                    self._paint(lines[0], value_style) if value_style else lines[0]
                )
                self._write(f"{' ' * value_indent}{first_value}")
            else:
                label_text = self._paint(
                    f"{label_prefix}{safe_label:<{LABEL_WIDTH}}{value_gap}", "secondary"
                )
                first_value = (
                    self._paint(lines[0], value_style) if value_style else lines[0]
                )
                self._write(f"{label_text}{first_value}")
            for line in lines[1:]:
                rendered_line = self._paint(line, value_style) if value_style else line
                self._write(f"{' ' * value_indent}{rendered_line}")
            return
        self._wrapped(safe_label, indent=ROW_INDENT)
        self._wrapped(
            rendered,
            indent=min(available, ROW_INDENT + ROW_GAP + 1),
            style=value_style,
        )

    def _reference_row(self, label: str, value: str) -> None:
        self._row(label, value)

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
        self._write("")
        self._section("OUTPUT")
        self._row("Status", "completed", value_style="success")
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
        self._write("")
        self._section("OUTPUTS")
        for item in self._outputs:
            name = safe_display_text(Path(item["audio"]).name)
            duration = _duration(item["duration"])
            output_value = f"{name}  {duration}" if duration is not None else name
            self._row("Audio", output_value)

    def finish_success(self) -> None:
        self._stop_waiting()
        self.event("Execution finished")
        self._write("")
        if self.dry_run:
            self._write(self._paint(f"{self.command.upper()} DRY RUN PREPARED", "title"))
            self._row("Generations prepared", self._prepared_count)
            self._row("Provider calls", 0)
        else:
            self._write(self._paint(f"{self.command.upper()} COMPLETED", "title"))
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
                self._row("Artifacts root", self._root)
        if self.dry_run:
            self._row("Elapsed", f"{self._elapsed():.1f}s")

    def _render_totals(self, key: str, label: str) -> None:
        total, available = self._sum_available(key)
        if available == 0:
            return
        completed = len(self._outputs)
        qualifier = "" if available == completed else " (partial)"
        self._row(label, f"{total:.1f}s{qualifier}")

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
        self._write(self._paint(f"{self.command.upper()} FAILED", "error"))
        total = self._planned_generations
        completed = self._generation_count
        if total is not None:
            self._row("Completed generations", f"{completed}/{total}")
            self._row("Failed", self._failed_count)
            self._row("Not executed", max(0, total - completed - self._failed_count))
        else:
            self._row("Completed generations", completed)
            self._row("Failed", self._failed_count)
            self._row("Not executed", "undetermined")
        self._row("Elapsed", f"{self._elapsed():.1f}s")
        self._summary_outputs()
        if self._current_run_dir is not None and self._current_run_dir.exists():
            self._row("Partial run folder", self._current_run_dir)
        if self._root is not None:
            self._row("Artifacts root", self._root)

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
        self._write(self._paint(f"{self.command.upper()} INTERRUPTED", "error"))
        self._row("Completed generations", self._generation_count)
        self._row("Failed / interrupted", self._failed_count)
        if self._planned_generations is not None:
            self._row(
                "Not executed",
                max(0, self._planned_generations - self._generation_count - self._failed_count),
            )
        self._summary_outputs()
        if self._root is not None:
            self._row("Artifacts root", self._root)

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
