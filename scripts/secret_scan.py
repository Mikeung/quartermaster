#!/usr/bin/env python3
"""Deterministic secret scanner — block secret-shaped strings from being committed.

Used two ways:
  - pre-commit hook (default): scans the STAGED content of changed files and
    exits non-zero if any token/key-shaped string is found, aborting the commit.
  - explicit files: `secret_scan.py path1 path2 ...` scans those working files
    (handy in CI or ad-hoc).

No dependencies, no network, deterministic. It only matches high-signal secret
shapes (provider keys, bot tokens, private-key blocks) to keep false positives
near zero; it is a backstop, not a replacement for keeping secrets in .env.
"""

from __future__ import annotations

import re
import subprocess
import sys

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Telegram bot token", re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b")),
    ("OpenAI/Anthropic API key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Private key block", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
]


def _scan(text: str) -> list[str]:
    return [name for name, pat in PATTERNS if pat.search(text)]


def _staged_files() -> list[str]:
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True,
    )
    return [f for f in r.stdout.split("\n") if f.strip()]


def _staged_content(path: str) -> str:
    r = subprocess.run(["git", "show", f":{path}"], capture_output=True, text=True)
    return r.stdout


def main(argv: list[str]) -> int:
    explicit = argv[1:]
    files = explicit or _staged_files()
    bad = False
    for f in files:
        try:
            content = open(f, errors="ignore").read() if explicit else _staged_content(f)
        except OSError:
            continue
        for name in _scan(content):
            print(f"BLOCKED: {f} contains a {name}", file=sys.stderr)
            bad = True
    if bad:
        print(
            "\nCommit blocked: secret-shaped content detected.\n"
            "Move secrets to .env (gitignored) — e.g. python scripts/set_secret.py KEY_NAME.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
