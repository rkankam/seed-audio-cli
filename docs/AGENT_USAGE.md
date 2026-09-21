# Agent usage

The CLI is intended to be safer for agents than direct curl calls.

## Discovery

An agent should start with:

    seed-audio --help
    seed-audio gen --help

Then read:

- AGENTS.md
- docs/CLI.md
- docs/RUN_FORMAT.md

## Recommended generation loop

1. Write or select a prompt file.
2. Select zero to three audio refs, or one image ref.
3. Dry-run.
4. Inspect JSON.
5. Execute the same command without --dry-run.
6. Read manifest.json for durable output locations and metadata.

Example:

    seed-audio gen       --prompt-file prompts/taxi.txt       --ref refs/driver.wav       --format wav       --sample-rate 48000       --dry-run       --json

Then:

    seed-audio gen       --prompt-file prompts/taxi.txt       --ref refs/driver.wav       --format wav       --sample-rate 48000       --json

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

    seed-audio replay runs/<run-id> --dry-run --json

then replay without --dry-run when execution is desired.

## Secrets

BYTEPLUS_API_KEY belongs in the environment only.

Agents must never copy it into:

- prompts
- YAML workflow files
- run folders
- issue bodies
- pull requests
- terminal transcript summaries
