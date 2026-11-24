from __future__ import annotations

import threading

from seed_audio_cli.reporting import ExecutionReporter, planned_generation_count, safe_display_text


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
