# Agent usage

The CLI is intended to be safer for agents than direct curl calls.

## Discovery

An agent should start with:

    uv run seed-audio --help
    uv run seed-audio gen --help

Then read:

- AGENTS.md
- docs/CLI.md
- docs/RUN_FORMAT.md

## Configuration

The CLI resolves BytePlus settings in this order:

1. process environment
2. .env in the current working directory
3. built-in default for the API URL only

Required secret:

    BYTEPLUS_API_KEY=...

Optional endpoint override:

    BYTEPLUS_SEED_AUDIO_URL=...

Never include either value in generated run artifacts. Run from the repository/workspace root when relying on .env.

## Recommended generation loop

1. Write or select a prompt file.
2. Select zero to three audio refs, or one image ref.
3. Dry-run.
4. Inspect JSON.
5. Execute the same command without --dry-run.
6. Read manifest.json for durable output locations and metadata.

Example:

    uv run seed-audio gen \
      --prompt-file prompts/taxi.txt \
      --ref refs/driver.wav \
      --format wav \
      --sample-rate 48000 \
      --dry-run \
      --json

Then:

    uv run seed-audio gen \
      --prompt-file prompts/taxi.txt \
      --ref refs/driver.wav \
      --format wav \
      --sample-rate 48000 \
      --json

## Parsing success

Example shape:

    {
      "ok": true,
      "runs": [
        {
          "ok": true,
          "run_id": "...",
          "run_dir": "runs/...",
          "audio": "runs/.../audio.wav",
          "manifest": "runs/.../manifest.json",
          "duration_seconds": 8.42,
          "billing_duration_seconds": 8.42,
          "request_id": "...",
          "provider_log_id": "..."
        }
      ]
    }

Never infer the canonical output filename when manifest.json is available.

## Parsing failure

Example:

    {
      "ok": false,
      "error": "Seed Audio supports at most 3 audio references"
    }

The process exits with code 2.

## Cost bounding

A single gen command may execute up to five variations.

A workflow may contain multiple jobs and therefore more calls. Always expand and validate unfamiliar workflow files with --dry-run before allowing a real run.

## Reproducibility

Do not manually reconstruct an old request from logs if the run directory exists. Use:

    uv run seed-audio replay runs/<run-id> --dry-run --json

then replay without --dry-run when execution is desired.

## Secrets

BYTEPLUS_API_KEY belongs in the process environment or .env in the current working directory.

Agents must never copy it into:

- prompts
- YAML workflow files
- run folders
- issue bodies
- pull requests
- terminal transcript summaries
