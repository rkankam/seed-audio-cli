# Release checklist

Use this checklist before publishing a public release.

- [ ] Run `uv run ruff check .` and `uv run pytest -q` from a clean clone.
- [ ] Run the README text-only, batch, and matrix dry-runs without credentials; confirm they make no provider calls.
- [ ] Review the pull request and wait for its CI checks before merging.
- [ ] Confirm release notes describe only provider validation actually performed. Seed Audio 1.0 is the only model covered by the validation documented here; dry-run does not validate provider compatibility for arbitrary model identifiers.
- [ ] Select and add a project license. No license is included in this remediation because the owner has not chosen one (REL-001).
- [ ] Verify the BytePlus account terms and rights for any media included in a release. No user media is bundled here.
- [ ] Create a version tag and release only after the owner authorizes publication.
