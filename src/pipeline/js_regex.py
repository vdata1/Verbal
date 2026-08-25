r"""JS-regex validity gate (scopes the corpus to constructible JS regexes).

The transpiler front-end is Python's ``sre_parse``, so it only accepts the Python
regex dialect. To keep the experiment honest we distinguish two failure kinds:

- ``not_js``  -- the pattern is not a constructible JS ``RegExp`` at all (under the
  flags the harnesses use). Out of scope; excluded cleanly, not counted as a bug.
- ``error``   -- the pattern IS a valid JS regex but Stage 1-3 failed on it (e.g.
  the transpiler can't parse a JS-only escape like ``\u{...}``). A real gap.

Validity is judged by NODE as the reference JS parser, under each pattern's
construction-affecting flags -- the ``/u`` a ``\p{...}``/``\u{...}`` pattern requires,
which the harness carries and which tightens escape rules (``js_construction_flags``;
EXPERIMENT_GAPS G1). Construction-level disagreements between engines are a separate
phenomenon, out of scope for this gate.

Fail loud: if node is missing or the probe fails, we raise -- we cannot scope the
experiment without the reference parser, and silently treating everything as
in-scope (or as not_js) would corrupt the results either way.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile

import paths

# Reference JS parser for the validity gate. Node is the conventional reference;
# recorded here (not buried in a call site) so the choice is explicit.
JS_VALIDITY_ENGINE = "node"


def classify_js(patterns: list[str], flags: list[str] | None = None) -> list[dict]:
    """Return ``[{"valid": bool, "error": str|None}, ...]`` aligned to `patterns`.

    Each pattern is validated under its construction-affecting flags ``flags[i]`` --
    the flags the harness will actually carry (in practice ``""`` or ``"u"``; see
    ``regex_facts.js_construction_flags``), so a pattern that requires ``/u`` is judged
    under ``/u`` where escape rules are stricter (EXPERIMENT_GAPS G1). ``flags=None``
    validates every pattern flagless -- the legacy behavior, kept for callers that do
    not specialize.

    One node invocation for the whole batch. Raises on a missing/failed probe.
    """
    if not patterns:
        return []
    if flags is None:
        flags = [""] * len(patterns)
    elif len(flags) != len(patterns):
        raise ValueError(
            f"flags ({len(flags)}) misaligned with patterns ({len(patterns)})"
        )
    entries = [{"src": p, "flags": fl} for p, fl in zip(patterns, flags)]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(entries, f)
        tmp = f.name
    try:
        proc = subprocess.run(
            [JS_VALIDITY_ENGINE, paths.JS_REGEX_PROBE, tmp],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            f"JS-regex validity gate needs '{JS_VALIDITY_ENGINE}' but it was not found"
        ) from e
    finally:
        os.unlink(tmp)

    if proc.returncode != 0:
        raise RuntimeError(
            f"JS-regex probe exited {proc.returncode}: {proc.stderr.strip()[:500]}"
        )

    results: dict[int, dict] = {}
    for line in proc.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        results[obj["i"]] = {"valid": obj["valid"], "error": obj["error"]}

    if len(results) != len(patterns):
        raise RuntimeError(
            f"JS-regex probe returned {len(results)} results for {len(patterns)} patterns"
        )
    return [results[i] for i in range(len(patterns))]
