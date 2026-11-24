# CLI reference

## seed-audio gen

Generate one or more independent outputs.

Exactly one prompt source is required:

    --prompt TEXT
    --prompt-file PATH

References:

    --ref PATH_OR_URL

Repeat --ref up to three times. Ordering is significant because prompts may refer to @Audio1, @Audio2 and @Audio3.

Image reference:

    --image PATH_OR_URL

Do not combine --image with --ref.

Output controls:

    --format wav|mp3|pcm|ogg_opus
    --sample-rate 8000|16000|24000|32000|44100|48000
    --speech-rate -50..100
    --loudness-rate -50..100
    --pitch-rate -12..12
    --subtitles
    --aigc-watermark

Experiment controls:

    -n, --variations 1..5
    --name NAME
    --runs-root PATH
    --out PATH
    --dry-run
    --json

--out creates an additional convenience copy. The canonical artifact remains inside the run directory.

`--dry-run` performs local validation and shows a redacted request without contacting BytePlus or requiring an API key. It does not verify that BytePlus supports an arbitrary `--model` value; Seed Audio 1.0 is the only model covered by the provider validation documented for this project.

## seed-audio replay

    seed-audio replay RUN_DIR

Options:

    --name NAME
    --runs-root PATH
    --out PATH
    --dry-run
    --json

Replay uses recipe.json and the copied refs inside RUN_DIR. Each local reference must stay inside the resolved run directory and match its recorded byte size and SHA-256 before request construction. Absolute paths, `..` traversal, escaping symlinks, missing references, and integrity mismatches fail before a provider call. Older recipes missing local integrity metadata are rejected because their contents cannot be verified.

Remote URLs are not copied. Userinfo, query parameters, and fragments are redacted from output and persisted artifacts. When a recipe records `url_redacted: true`, supply a fresh URL with `gen`; the redacted recipe cannot replay that reference.

## seed-audio batch

    seed-audio batch workflow.yaml

Batch file:

    jobs:
      - id: first
        prompt: "..."
        variations: 2
        output:
          format: wav
          sample_rate: 48000

A job may use prompt_file instead of prompt. Relative paths are resolved from the YAML file directory.

## seed-audio matrix

    seed-audio matrix matrix.yaml

Matrix file:

    base:
      output:
        format: wav
        sample_rate: 48000

    variations: 2

    runs:
      - id: neutral
        prompt_file: prompts/neutral.txt

      - id: aggressive
        prompt_file: prompts/aggressive.txt
        output:
          format: mp3
          sample_rate: 44100

Each run inherits base values and may override them.

## Exit behavior

0: command completed successfully

2: validation, local I/O, provider or persistence failure

In JSON mode, stdout remains parseable JSON on both success and failure.

Batch and matrix jobs run sequentially and stop at the first error. Their error result does not enumerate successful earlier jobs, and no live progress events are emitted; inspect existing run folders before retrying.
