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
    cp .env.example .env

Set BYTEPLUS_API_KEY in .env, or export it in the shell. Environment variables take precedence over .env.

The CLI reads .env only from the current working directory. Run commands from the repository/workspace root when relying on .env.

The default endpoint is:

    https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create

BYTEPLUS_SEED_AUDIO_URL can override it from either the environment or .env, primarily for testing.

For agent and local development workflows, prefer uv run seed-audio ...; it does not require activating .venv first. The shorter seed-audio ... form works when the virtual environment is already active.

## Quick start

Text only:

    uv run seed-audio gen --prompt "Rain outside a small late-night station." --out take.wav

Prompt file plus local audio reference:

    uv run seed-audio gen \
      --prompt-file prompts/scene.txt \
      --ref refs/driver.wav \
      --format wav \
      --sample-rate 48000

Image reference:

    uv run seed-audio gen \
      --prompt-file prompts/character.txt \
      --image refs/character.png

Validate without calling BytePlus:

    uv run seed-audio gen --prompt-file prompts/scene.txt --ref refs/driver.wav --dry-run --json

Generate three independent variations:

    uv run seed-audio gen --prompt-file prompts/scene.txt --ref refs/driver.wav -n 3

Replay a previous run:

    uv run seed-audio replay runs/20260921T030000Z_scene_01

Batch and matrix examples are in examples/.

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

recipe.json is the replayable local recipe. request.json is a readable representation of the actual provider request with large Base64 media values redacted. response.json similarly redacts the returned Base64 audio. The generated audio is always persisted locally because provider URLs are temporary.

See docs/RUN_FORMAT.md for the stable schema.

## Agent use

AGENTS.md is the first document an autonomous coding or generation agent should read. docs/AGENT_USAGE.md documents the machine-oriented CLI contract.

## Status

Initial implementation. Text-only generation and local @Audio1 reference generation have both been smoke-tested successfully against the official BytePlus endpoint.

The CLI intentionally wraps a narrow official API surface instead of becoming a generic TTS framework.
