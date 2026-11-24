from __future__ import annotations

import threading

import pytest

from seed_audio_cli.models import SeedAudioRequest
from seed_audio_cli.reporting import (
    ExecutionReporter,
    generation_counter,
    planned_generation_count,
    safe_display_text,
    visible_width,
    wrap_visible,
)


def test_display_sanitization_redacts_urls_credentials_base64_and_controls() -> None:
    value = (
        "https://user:pass@example.test/a.wav?token=query-secret "
        "api_key=inline-secret audio_data='QUJDREVGR0g=' "
        "audio='QUJDREVGR0g=' data:image/png;base64,QUJDREVGR0g=\x1b[31m"
    )

    rendered = safe_display_text(value)

    assert "https://example.test/a.wav" in rendered
    assert "query-secret" not in rendered
    assert "inline-secret" not in rendered
    assert "QUJDREVGR0g=" not in rendered
    assert "\x1b" not in rendered
    assert "␛" in rendered


def test_wait_counter_uses_injected_monotonic_clock_and_stops_cleanly() -> None:
    current_time = [10.0]
    wait_lines: list[str] = []
    wait_line_seen = threading.Event()
    wait_calls = [0]

    def writer(line: str) -> None:
        wait_lines.append(line)
        if "Awaiting API response..." in line:
            wait_line_seen.set()

    def fake_wait(stop: threading.Event, interval: float) -> bool:
        if wait_calls[0] == 0:
            wait_calls[0] += 1
            current_time[0] += 1.25
            return False
        return stop.wait(interval)

    reporter = ExecutionReporter(
        command="gen",
        dry_run=False,
        as_json=False,
        writer=writer,
        clock=lambda: current_time[0],
        wait_interval=0.001,
        wait_fn=fake_wait,
    )
    reporter.start()
    reporter.request_started("synthetic-request-id")

    assert wait_line_seen.wait(timeout=1)
    reporter.provider_response_received("synthetic-log-id")
    reporter.close()

    assert any("Awaiting API response... 1.2s" in line for line in wait_lines)
    assert any("API response received (1.2s)" in line for line in wait_lines)
    assert not any(
        thread.name == "seed-audio-reporting-wait" for thread in threading.enumerate()
    )


def test_planned_generation_count_does_not_validate_a_workflow_early() -> None:
    assert planned_generation_count([{"variations": 2}, {}]) == 3
    assert planned_generation_count([{"variations": "invalid"}]) is None
    assert planned_generation_count([{"variations": 0}]) is None


def test_generation_counters_use_a_consistent_minimum_width() -> None:
    assert generation_counter(1, 1) == "[01/01]"
    assert generation_counter(1, 6) == "[01/06]"
    assert generation_counter(2, 6) == "[02/06]"
    assert generation_counter(1, None) == "[01/??]"
    assert generation_counter(100, 100) == "[100/100]"


def test_long_row_labels_keep_values_in_a_shared_column() -> None:
    lines: list[str] = []
    reporter = ExecutionReporter(
        command="gen",
        dry_run=False,
        as_json=False,
        writer=lines.append,
        terminal_width=100,
        color_enabled=False,
    )

    reporter._row("Status", "completed")
    reporter._row("API elapsed", "13.4s")
    reporter._row("Generation elapsed", "13.5s")
    reporter._row("Audio duration", "12.3s")

    expected_values = ("completed", "13.4s", "13.5s", "12.3s")
    value_columns = [
        line.index(value)
        for line, value in zip(lines, expected_values, strict=True)
    ]
    assert len(set(value_columns)) == 1
    assert value_columns[0] == 25


def test_wrapping_uses_terminal_cells_and_preserves_words_at_multiple_widths() -> None:
    text = "A café 漢字 e\u0301 👩\u200d🚀 ending"
    for width in (12, 20, 40, 80, 100):
        lines = wrap_visible(text, width)
        assert "".join(lines).replace(" ", "") == text.replace(" ", "")
        assert all(visible_width(line) <= width for line in lines)
    assert wrap_visible("A  prompt", 20) == ["A  prompt"]

    long_word = "abcdefghijklmno"
    chunks = wrap_visible(long_word, 6)
    assert "".join(chunks) == long_word
    assert all(visible_width(line) <= 6 for line in chunks)


def test_visible_width_ignores_ansi_and_counts_combining_and_wide_characters() -> None:
    assert visible_width("\x1b[1;36mTitle\x1b[0m") == 5
    assert visible_width("e\u0301") == 1
    assert visible_width("漢字") == 4
    assert visible_width("👩\u200d🚀") == 2


def test_prompt_wrapping_keeps_intentional_multiline_breaks() -> None:
    lines: list[str] = []
    reporter = ExecutionReporter(
        command="gen",
        dry_run=False,
        as_json=False,
        writer=lines.append,
        terminal_width=30,
        color_enabled=False,
    )

    reporter.show_inputs(
        request=SeedAudioRequest(
            text_prompt="First prompt line wraps over several words.\n\nDeuxième ligne avec 漢字."
        ),
        references=[],
    )

    prompt_start = lines.index("  Text prompt") + 1
    references_start = lines.index("  References")
    prompt_lines = lines[prompt_start:references_start]
    assert prompt_lines[:-1].count("") == 1
    assert any("First prompt" in line for line in prompt_lines)
    assert any("Deuxième ligne" in line for line in prompt_lines)
    assert all(visible_width(line) <= 30 for line in lines if line)


def test_semantic_colors_can_be_enabled_or_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    colored: list[str] = []
    reporter = ExecutionReporter(
        command="gen",
        dry_run=False,
        as_json=False,
        writer=colored.append,
        color_enabled=True,
    )
    reporter.start()
    reporter.event("Input validated")
    reporter.event("Awaiting API response... 1.0s")
    reporter.event("Generation failed during provider request: synthetic failure")

    joined = "\n".join(colored)
    assert "\x1b[1;36m" in joined
    assert "\x1b[32m" in joined
    assert "\x1b[33m" in joined
    assert "\x1b[31m" in joined
    assert "\x1b[90m" in joined

    plain: list[str] = []
    ExecutionReporter(
        command="gen",
        dry_run=False,
        as_json=False,
        writer=plain.append,
        color_enabled=False,
    ).start()
    assert all("\x1b" not in line for line in plain)


def test_no_color_disables_ansi_even_when_color_is_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    lines: list[str] = []
    reporter = ExecutionReporter(
        command="gen",
        dry_run=False,
        as_json=False,
        writer=lines.append,
        color_enabled=True,
    )

    reporter.start()
    reporter.event("Input validated")

    assert all("\x1b" not in line for line in lines)


def test_untrusted_terminal_controls_are_neutralized_before_reporter_styles() -> None:
    lines: list[str] = []
    reporter = ExecutionReporter(
        command="gen",
        dry_run=False,
        as_json=False,
        writer=lines.append,
        color_enabled=True,
    )

    reporter.event("Input validated \x1b[2J\u202e synthetic")

    joined = "\n".join(lines)
    assert "\x1b[2J" not in joined
    assert "␛[2J" in joined
    assert "\u202e" not in joined
