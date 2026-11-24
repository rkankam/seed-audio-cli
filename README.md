# seed-audio-cli

A small, reproducible, agent-friendly CLI for the official BytePlus Seed Audio 1.0 API.

The project deliberately focuses on direct audio creation with text prompts plus optional audio or image references. It does not implement BytePlus preset or registered speaker IDs.

## Goals

- one obvious command for a generation
- local media references with automatic Base64 encoding
- dry-run validation before spending credits
- deterministic run folders with prompts, request/response sidecars and hashes
- replay from a previous run
- bounded variations
- YAML batch and matrix workflows
- stable JSON output for agents

## Install

    uv sync --extra dev

For real generation, set BYTEPLUS_API_KEY in the process environment or in a .env file in the current working directory. Process environment values take precedence.

The CLI reads .env only from the current working directory. Run commands from the repository/workspace root when relying on .env.

The default endpoint is:

    https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create

BYTEPLUS_SEED_AUDIO_URL can override it from either the environment or .env, primarily for testing.

For agent and local development workflows, prefer uv run seed-audio ...; it does not require activating .venv first. The shorter seed-audio ... form works when the virtual environment is already active.

## Quick start

Start with a free text-only validation. It needs no API key or external files and makes no provider request:

    uv run seed-audio gen --prompt "Rain outside a small late-night station." --dry-run --json

Validate the published batch and matrix examples without a key or provider calls:

    uv run seed-audio batch examples/batch.yaml --dry-run --json
    uv run seed-audio matrix examples/matrix.yaml --dry-run --json

### Real generation

Generation sends a request to BytePlus and may consume credits:

    uv run seed-audio gen --prompt "Rain outside a small late-night station." --out take.wav

### User-provided references

Reference examples require files you provide. Replace the path with a valid local file or URL, then dry-run before any real call:

    uv run seed-audio gen --prompt "A calm spoken greeting." --ref /path/to/your/reference.wav --dry-run --json

Audio and image references are mutually exclusive. Up to three audio references or one image reference are supported.

Replay a previous run:

    uv run seed-audio replay runs/20260921T030000Z_scene_01

Batch and matrix examples are in examples/.

## Execution feedback

By default, `gen`, `replay`, `batch`, and `matrix` print a chronological terminal
log. Each generation shows its effective model, full prompt, references and
available local media metadata, audio settings, execution stages, persisted
artifact paths, and result metadata. Repeated variations show their inputs in
full each time. Dry-runs show the prepared plan and explicitly report that no
provider call was made.

While a synchronous provider request is pending, the CLI prints elapsed local
time once per second. This measures only time spent waiting in this CLI; it is
not provider progress or a remaining-time estimate. With `--json`, stdout
contains only the existing final JSON result and the human execution log goes
to stderr.

Prompts and local paths can contain personal information. Review terminal logs
before sharing them publicly.

## Run artifact contract

Every successful provider call creates an immutable run folder:

    runs/<run-id>/
      audio.<ext>
      prompt.txt
      recipe.json
      request.json
      response.json
      manifest.json
      subtitles.json        # only when returned
      refs/                 # copied local references

recipe.json is the replayable local recipe. request.json is a readable representation of the actual provider request with large Base64 media values redacted. response.json similarly redacts the returned Base64 audio. Sensitive URL userinfo, query parameters, and fragments are removed from output and persisted metadata. A remote reference marked as redacted must be supplied again before replay. The generated audio is always persisted locally because provider URLs are temporary.

See docs/RUN_FORMAT.md for the stable schema.

## Agent use

AGENTS.md is the first document an autonomous coding or generation agent should read. docs/AGENT_USAGE.md documents the machine-oriented CLI contract.

## Status

The only model covered by the provider validation documented for this project is Seed Audio 1.0. A successful dry-run validates local CLI input and request construction; it does not confirm that BytePlus accepts an arbitrary model identifier. This remediation used synthetic fixtures and local mocks and adds no provider validation.

Batch and matrix jobs run sequentially and stop at the first error. The human
log reports earlier generations that completed and were persisted, the failed
generation when known, and generations that did not execute. Its wait counter
shows local elapsed time only; it does not expose provider-internal progress.
Generated audio is not guaranteed to be identical across replays because
provider behavior and model implementations can change.

Before publishing, choose a project license. No license is included because the owner has not selected one; see [the release checklist](docs/RELEASE_CHECKLIST.md).

The CLI intentionally wraps a narrow official API surface instead of becoming a generic TTS framework.
