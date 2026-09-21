# AGENTS.md

This repository is designed to be used by both humans and autonomous agents.

## Mission

Provide a narrow, reliable CLI around the official BytePlus Seed Audio 1.0 audio-creation endpoint.

Do not turn this repository into a generic TTS framework.

## Scope locks

1. Do not add preset, registered, or cloned speaker IDs.
   The supported reference modalities are:
   - zero to three audio references
   - exactly one image reference
   Audio and image references are mutually exclusive.

2. The BytePlus call is synchronous.
   Do not add submit/status/poll abstractions unless the official API contract changes.

3. BYTEPLUS_API_KEY must come from the environment.
   Never accept it as a command-line option, write it to a run folder, log it, or commit it.

4. Preserve the run artifact contract in docs/RUN_FORMAT.md.
   Existing run folders must remain replayable after compatible changes.

5. Provider URLs are temporary.
   Persist generated audio locally before reporting success.

6. Do not silently truncate prompts or references to satisfy provider limits.
   Reject invalid input with a clear error.

7. Keep variation counts bounded.
   The CLI currently permits 1 to 5 provider calls per job.

## Agent workflow

Before a provider call:

    seed-audio gen ... --dry-run --json

For a workflow:

    seed-audio matrix examples/matrix.yaml --dry-run --json

Only remove dry-run after validation when a real generation is explicitly intended.

## Development

Install:

    python -m pip install -e ".[dev]"

Run:

    ruff check .
    pytest

When changing the provider contract:

- update src/seed_audio_cli/models.py
- update docs/BYTEPLUS_API.md
- update tests
- keep README examples valid

## Machine output

With --json, stdout is a single JSON object.

Success:

    {"ok": true, ...}

Failure:

    {"ok": false, "error": "..."}

A failure exits with code 2.

Do not add decorative text to stdout in JSON mode.

## Provider request IDs

Every real provider call receives a new UUID in X-Api-Request-Id. Replay means replaying the same logical recipe, not reusing the old provider request ID.

## Reference naming

In prompts, BytePlus audio references are addressed in request order as @Audio1, @Audio2 and @Audio3. The CLI preserves the order supplied with repeated --ref options.

## Cost awareness

A batch, matrix, or variation command may issue multiple paid calls. Agents should inspect the expanded plan with --dry-run before a real run when changing a workflow.
