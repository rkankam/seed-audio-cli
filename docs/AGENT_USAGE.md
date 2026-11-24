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

1. Validate an autonomous text-only request first:

       uv run seed-audio gen --prompt "A short neutral test sound." --dry-run --json

2. For workflows, inspect the plan without a key:

       uv run seed-audio batch examples/batch.yaml --dry-run --json
       uv run seed-audio matrix examples/matrix.yaml --dry-run --json

3. For a real generation, write or select a prompt, then select zero to three audio refs or one image ref.
4. Dry-run and inspect the redacted JSON.
5. Execute without `--dry-run` only when a provider call and potential charge are intended.
6. Read manifest.json for durable output locations and metadata.

Text-only dry-run:

    uv run seed-audio gen \
      --prompt "A restrained late-night taxi announcement." \
      --dry-run \
      --json

When a provider call and potential charge are intended, run the chosen text-only command without `--dry-run`:

    uv run seed-audio gen \
      --prompt "A restrained late-night taxi announcement." \
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

## Execution log

Commands print an append-only human log by default. With `--json`, the log is
sent to stderr and stdout contains only the existing JSON result. Agents should
parse stdout and capture stderr separately when execution feedback is useful.

Each generation repeats its effective inputs, including the full prompt,
available reference metadata, and values in the prepared provider request. A
dry-run shows the prepared plan and states that no provider call was made. While
a synchronous request is pending, periodic lines show elapsed local time; they
do not indicate provider progress or remaining time. Prompts and local paths
can contain personal information, so review logs before sharing them.

## Cost bounding

A single gen command may execute up to five variations.

A workflow may contain multiple jobs and therefore more calls. Always expand and validate unfamiliar workflow files with --dry-run before allowing a real run.

## Reproducibility

Do not manually reconstruct an old request from logs if the run directory exists. Use:

    uv run seed-audio replay runs/<run-id> --dry-run --json

then replay without --dry-run when execution is desired.

Replay only reads local references inside the run directory and checks their recorded size and SHA-256 before request construction. It rejects absolute paths, parent traversal, escaping symlinks, missing metadata, and changed files. Remote URLs with redacted userinfo, query, or fragment require a new valid URL; old recipes without a redaction marker remain usable while their original URL remains valid.

A dry-run confirms local validation and request construction, not provider compatibility of an arbitrary model identifier. Seed Audio 1.0 is the only model covered by the provider validation documented for this project. Replay also cannot guarantee identical generated audio because provider behavior may change.

URLs may contain temporary credentials. Their userinfo, query, and fragments are redacted in output and persisted run metadata. Older run folders created before URL redaction may still contain complete URLs and should be handled as sensitive data. Generated audio URLs are temporary; the CLI downloads the audio before reporting success.

Batch and matrix workflows are sequential and stop on the first error. The
human log reports earlier generations that completed and were persisted, the
generation that failed when known, and generations that did not execute.
Inspect run manifests before retrying a failed workflow.

## Secrets

BYTEPLUS_API_KEY belongs in the process environment or .env in the current working directory.

Agents must never copy it into:

- prompts
- YAML workflow files
- run folders
- issue bodies
- pull requests
- terminal transcript summaries
