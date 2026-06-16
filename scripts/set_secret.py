#!/usr/bin/env python3
"""Set a secret in .env without exposing its value.

Run this in YOUR OWN terminal:

    python scripts/set_secret.py TELEGRAM_BOT_TOKEN

It prompts for the value with the input HIDDEN (no echo), then writes/updates
that key in `.env` at mode 600, preserving every other line. The value is never
printed, never passed on the command line (so it stays out of shell history),
and never logged. Re-running updates the key in place (idempotent).

This is the painless, secure way to rotate a token: no manual file editing, and
the secret only ever lives in .env — never in a transcript.
"""

from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_KEY_RE = re.compile(r"[A-Z][A-Z0-9_]*")


def main() -> int:
    if len(sys.argv) != 2 or not _KEY_RE.fullmatch(sys.argv[1]):
        print("usage: set_secret.py KEY_NAME   (e.g. TELEGRAM_BOT_TOKEN)", file=sys.stderr)
        return 2
    key = sys.argv[1]

    value = getpass.getpass(f"Paste value for {key} (input hidden, not echoed): ").strip()
    if not value:
        print("Empty value — aborted, nothing written.", file=sys.stderr)
        return 1

    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    out: list[str] = []
    replaced = False
    assign = re.compile(rf"\s*{re.escape(key)}\s*=")
    for line in lines:
        if assign.match(line):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")

    # Write atomically-ish, then lock down permissions to owner-only.
    ENV_PATH.write_text("\n".join(out) + "\n")
    os.chmod(ENV_PATH, 0o600)

    action = "Updated" if replaced else "Added"
    print(f"{action} {key} in {ENV_PATH} (mode 600). Value not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
