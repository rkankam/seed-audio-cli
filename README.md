# seed-audio-cli

An independent Python CLI for creating audio with BytePlus Seed Audio 1.0. It
uses BytePlus's official API; it is not developed or maintained by BytePlus.

## Features

- Text-to-audio generation with optional audio or image references.
- Local file and remote URL references: up to three audio references or one
  image reference per request. The two reference types cannot be combined.
- Explicit and implicit AIGC watermark configuration, including provider
  metadata fields.
- YAML batch and matrix workflows, with one to five variations per job.
- Replayable run folders with request and response records, manifests, and
  copied local references.
- Local-reference confinement and size/SHA-256 checks during replay.
- Redaction of sensitive URL components in CLI output and saved metadata.
- A chronological terminal log for inputs, execution stages, waiting, and
  persisted results.
- Machine-readable JSON output for scripts and agents.
- Credential-free dry-runs that validate local inputs and construct the
  provider request without making a provider call.

## Install from source

Requirements: Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

    git clone https://github.com/rkankam/seed-audio-cli.git
    cd seed-audio-cli
    uv sync --extra dev

The command is available as `uv run seed-audio ...` from the checkout.

For real generation, set `BYTEPLUS_API_KEY` in the process environment or in a
`.env` file in the current working directory. A process environment value takes
precedence. The default endpoint is BytePlus's Seed Audio 1.0 creation API;
`BYTEPLUS_SEED_AUDIO_URL` can override it for testing.

## Quickstart without credits

Validate a text-only request locally:

    uv run seed-audio gen --prompt "Rain outside a small late-night station." --dry-run --json

The dry-run needs no API key, sends no provider request, and consumes no
generation credits. It checks local inputs and request construction; it does
not check whether BytePlus supports an arbitrary model identifier.

The included workflow examples can also be expanded without credentials or
provider calls:

    uv run seed-audio batch examples/batch.yaml --dry-run --json
    uv run seed-audio matrix examples/matrix.yaml --dry-run --json

## Generate audio

After reviewing a dry-run, run a real generation only when a provider call is
intended. It requires a valid API key and may consume credits:

    uv run seed-audio gen --prompt "Rain outside a small late-night station." --out take.wav

Every successful call is saved to a run folder under `runs/`. `--out` creates
an additional convenience copy; the run folder remains the canonical output.

## Media references

Use `--ref PATH_OR_URL` for audio and repeat it for up to three references.
Use `--image PATH_OR_URL` for one image reference. Do not combine `--image`
with `--ref`. Remote references are passed to the provider and are not
downloaded just to produce reporting metadata.

For example, validate a local reference before generation:

    uv run seed-audio gen --prompt "A calm spoken greeting." --ref /path/to/reference.wav --dry-run --json

Reference paths and prompts may contain personal information. Review terminal
logs and shared command output before making them public.

## Batch and matrix workflows

`batch` runs an ordered list of independent jobs. `matrix` resolves shared
values from a base configuration and allows each run to override them. Both
formats support bounded variations and run sequentially, stopping at the first
error.

    uv run seed-audio batch examples/batch.yaml --dry-run --json
    uv run seed-audio matrix examples/matrix.yaml --dry-run --json

See [docs/CLI.md](docs/CLI.md) for the YAML fields and command options. See
[docs/API_COVERAGE.md](docs/API_COVERAGE.md) for the provider coverage matrix,
intentional exclusions, and the Seed Audio 1.5 decision boundary.

## Replay and traceability

Each successful provider call creates a run folder containing the recipe,
request and response records, manifest, generated audio, and copied local
references when applicable. The manifest records artifact paths, media
integrity values, durations, request ID, and provider log ID when available.

Replay a run after inspecting its local plan:

    uv run seed-audio replay runs/<run-id> --dry-run --json

Replay confines local references to the run folder and verifies their recorded
size and SHA-256 before request construction. Remote URL credentials, query
parameters, and fragments are redacted in output and saved metadata. If a
recipe records a redacted URL, provide a fresh URL for a new generation.
Generated audio is persisted locally because provider URLs are temporary. See
[docs/RUN_FORMAT.md](docs/RUN_FORMAT.md) for the artifact contract.

## Execution log

By default, `gen`, `replay`, `batch`, and `matrix` print an append-only
chronological log. It repeats each generation's effective inputs and reports
the stages that actually occur, saved artifact paths, and available result
metadata. While the synchronous provider request is pending, periodic lines
show elapsed time measured locally by the CLI. This is not provider progress
or a remaining-time estimate.

With `--json`, stdout contains only the existing JSON result and the human log
goes to stderr. Redirect or capture the streams separately when parsing output.
See [docs/AGENT_USAGE.md](docs/AGENT_USAGE.md) for agent-oriented examples.

## Limitations

- Seed Audio 1.0 is the only model covered by the provider validation
  documented for this project. A dry-run does not verify provider support for
  an arbitrary model identifier.
- Batch and matrix workflows are sequential and fail fast. There is no retry,
  parallel execution, or workflow resume behavior.
- Generated audio is not guaranteed to be identical across replays because
  provider behavior and model implementations can change.
- The CLI does not implement preset, registered, or cloned speaker IDs.

## License

This project is distributed under the MIT License. See [LICENSE](LICENSE).
