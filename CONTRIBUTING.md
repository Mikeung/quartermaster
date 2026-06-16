# Contributing

Thanks for your interest. This project is an advisory-only operational
intelligence engine; contributions should preserve that character.

## Development setup

```bash
git clone https://github.com/Mikeung/quartermaster
cd quartermaster
python -m venv venv && . venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # adjust locally; never commit .env
make check                  # ruff + mypy + pytest
```

## Before you open a PR

Run the full gate and make sure it passes:

```bash
make lint        # ruff check .
make typecheck   # mypy on the typed packages
make test        # pytest tests/
```

- **Add tests** for every new feature or bug fix. Detectors and scanners need
  tests for edge cases (empty input, missing permissions, absent tools).
- **Keep it deterministic.** Same input → same output. Reach for an LLM only when
  the problem genuinely needs one, and make it injectable so it stays testable.
- **No new heavy dependencies** without discussion.

## Principles (these don't change)

- **Advisory only.** Observe, analyze, recommend — never modify infrastructure,
  deploy, or auto-remediate. New features must fail safe and stay opt-in.
- **Evidence over inference.** Every claim carries answer + confidence + evidence.
  "Unknown" is a valid answer; never fabricate.
- **Read-only by default.** The only writable paths are `data/` and `reports/`.
- **Secrets:** read from env only; never log, return, or commit them. See
  [SECURITY.md](SECURITY.md).
- **Simplicity first.** Prefer a boring, deterministic solution. Avoid speculative
  abstractions.

## Commits & PRs

- Small, focused, descriptive commits.
- Describe what changed and why; note test coverage and any operational impact.
- One logical change per PR; don't bundle unrelated refactors.

## Reporting bugs

Open a GitHub issue with: what you ran, what you expected, what happened, and the
relevant log output (with any secrets redacted). For security issues, see
[SECURITY.md](SECURITY.md) — do not file a public issue.
