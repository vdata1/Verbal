#!/usr/bin/env python3
"""Fail loud if the container's JS engines do not match the recorded pins.

The pins are baked into <repo>/.engine-pins.json at image-build time from the
Dockerfile ARGs: the exact engine versions that produced the reported results.
Verifying at container start guarantees the image being run matches the one being
claimed, which is the whole point of pinning.

Compares the semantic version number only (e.g. 2.9.1), not the full banner:
deno reports its platform triple in the version string, and that difference is
expected and irrelevant to the pin.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

# Repo-relative rather than hardcoded to /app, so the pins resolve both in the
# image and in a native install at any prefix. Nothing outside the Docker
# entrypoint runs this automatically, so a native run should invoke it directly.
PINS_FILE = Path(__file__).resolve().parent.parent / ".engine-pins.json"

# Only the version is needed here; the eval's invocation argv lives in
# eval/run_eval.py:ENGINE_CMD and is deliberately not duplicated.
VERSION_CMD = {
    "node": ["node", "--version"],
    "bun": ["bun", "--version"],
    "deno": ["deno", "--version"],
}


def semver(text: str) -> str | None:
    """First dotted x.y.z in `text` (handles 'v26.5.0', 'deno 2.9.1 (...)', '1.3.14')."""
    m = re.search(r"(\d+\.\d+\.\d+)", text or "")
    return m.group(1) if m else None


def main() -> int:
    try:
        with open(PINS_FILE) as f:
            pins = json.load(f)
    except FileNotFoundError:
        sys.stderr.write(
            f"no pins file at {PINS_FILE} -- refusing to run for reproducibility.\n"
            "The Docker build writes it; a native install writes it in "
            "lxc_provision.sh (it is untracked, so a fresh clone lacks it).\n"
        )
        return 1

    problems = []
    for engine, want_raw in pins.items():
        want = semver(want_raw) or want_raw
        try:
            out = subprocess.run(VERSION_CMD[engine], capture_output=True, text=True, timeout=30)
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            problems.append(f"{engine}: could not run --version ({type(e).__name__})")
            continue
        got = semver(out.stdout)
        if got != want:
            banner = (out.stdout.strip().splitlines() or ["<no output>"])[0]
            problems.append(f"{engine}: pinned {want}, found {got!r} (banner: {banner!r})")

    if problems:
        sys.stderr.write("ENGINE VERSION MISMATCH -- refusing to run for reproducibility:\n")
        for p in problems:
            sys.stderr.write(f"  - {p}\n")
        sys.stderr.write(
            "Rebuild the image (docker compose build) or re-pin the ARGs in the "
            "Dockerfile deliberately; do not run against unpinned engines.\n"
        )
        return 1

    ok = ", ".join(f"{k}={semver(v) or v}" for k, v in pins.items())
    print(f"engine pins OK: {ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
