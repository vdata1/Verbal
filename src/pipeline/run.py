r"""Pipeline driver -- runs Stages 1-3 over a corpus window, uniformly.

Reads the corpus and flows every regex through the same path: base spec ->
specialize (per API) -> generate strings + harnesses. Nothing branches on regex
id or API name.

Every regex gets a recorded per-regex outcome; there are no silent skips:

- ``skipped_non_regex``  the row's ``pattern`` is not a string. Not a regex;
  recorded and counted, not an error.
- ``not_js``             the pattern is not a constructible JS ``RegExp`` under the
  flags its harness will carry, per the reference-engine gate in ``js_regex.py``.
  Out of scope for a JS differential test; excluded cleanly, not a bug.
- ``error``              the pattern is a valid JS regex but a stage raised (e.g.
  the transpiler cannot parse a JS-only escape). The exception is recorded as this
  regex's outcome and the sweep continues: each regex is an independent unit and
  its failure is a result, not a crash.
- ``unsatisfiable``      Stage-1 analysis proves the regex matches nothing (an
  internal ``$``/``^`` pins a line boundary where a non-newline literal is
  required, typically an unexpanded ``$var`` template). No matching strings exist,
  so generation stops after the base spec.
- ``unsupported_unicode_property``  the pattern uses a ``\p{...}``/``\pX`` property
  the authoritative resolver does not know. Recorded by name rather than
  mis-compiled. Every known property is rewritten to an exact explicit char set.
- ``surrogate_escape_unmodeled``  the pattern contains a UTF-16 surrogate code
  point (U+D800..U+DFFF). Pairing is not modelled; recorded rather than crashing
  on the un-encodable lone surrogate.
- ``no_inputs``          every API specialized but the fuzzer generated zero
  strings on all of them, typically a large char class with unbounded repetition
  that exhausts ``fuzz_timeout_s``. Kept distinct from ``ok`` so it is not counted
  as evaluated.
- ``ok``                 all APIs specialized and at least one input generated.

Malformed corpus JSON is bad data, not a per-regex outcome, and raises.
"""

from __future__ import annotations

import json
import os
import traceback

from pipeline.api_descriptors import DESCRIPTORS
from pipeline.base_spec import write_base_spec
from pipeline.config import Config, provenance, set_chunk_context
from pipeline.js_regex import classify_js
from pipeline.regex_facts import js_construction_flags
from pipeline.specialize import write_specialization
from pipeline.generate import generate_for_api
from regex_fandango_transpiler import UnsupportedUnicodeProperty, SurrogateEscapeUnmodeled
import paths


def load_corpus(config: Config) -> list[dict]:
    """Load the corpus into a list of row dicts, order preserved.

    Two accepted formats, distinguished by the first non-whitespace character:

    - a JSON array of pattern strings (``["a+", "^b$"]``) -- the paper corpus;
      each element becomes a ``{"pattern": ...}`` row.
    - JSON Lines, one object per line, each with a ``pattern`` field.

    A row whose ``pattern`` is not a string is kept: ``process_row_range``
    classifies it as ``skipped_non_regex``. Malformed JSON raises.
    """
    with open(config.corpus_path, "r") as f:
        text = f.read()
    head = text.lstrip()[:1]

    if head == "[":
        try:
            items = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"{config.corpus}: invalid JSON array: {e}") from e
        rows = []
        for i, item in enumerate(items):
            if isinstance(item, dict):
                rows.append(item)
            elif isinstance(item, str):
                rows.append({"pattern": item})
            else:
                raise ValueError(f"{config.corpus} item {i}: expected a string or "
                                 f"object, got {type(item).__name__}")
        return rows

    rows = []
    for lineno, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{config.corpus} line {lineno}: invalid JSON: {e}") from e
    return rows


def _process_regex(index: int, pattern: str, config: Config) -> dict:
    """Run Stages 1-3 for one regex. Returns per-API generation summaries.

    If Stage-1 analysis proves the regex matches nothing, stop after the base spec
    rather than generating strings that can never match.
    """
    rid = paths.regex_id(index)
    _, num_constraints, capture_group_rules, facts = write_base_spec(pattern, rid, config)
    facts_record = {"anchored_single_match": facts.anchored_single_match,
                    "requires_flags": sorted(facts.requires_flags),
                    "unsatisfiable_internal_anchor": facts.unsatisfiable_internal_anchor}
    if facts.unsatisfiable_internal_anchor:
        return {"unsatisfiable": True, "num_constraints": num_constraints,
                "capture_group_rules": list(capture_group_rules),
                "regex_facts": facts_record, "apis": []}
    apis = []
    for descriptor in DESCRIPTORS:
        spec = write_specialization(rid, descriptor, pattern, config, facts)
        gen = generate_for_api(rid, descriptor, pattern, config, facts)
        apis.append({
            "api": descriptor.api, "pad": spec.pad, "flags": spec.flags,
            "degenerate": spec.degenerate,
            "anchored_single_match": spec.anchored_single_match,
            "reason": spec.reason, "num_strings": gen["num_strings"],
        })
    return {"num_constraints": num_constraints,
            "capture_group_rules": list(capture_group_rules),
            "regex_facts": facts_record,
            "apis": apis}


def process_row_range(rows: list[dict], start: int, config: Config) -> list[dict]:
    """Run Stages 1-3 over ``rows`` whose global corpus ids are ``start .. start+len-1``.

    The single per-regex loop, so every regex flows the same code path regardless
    of how the corpus is sliced. Ids are always ``regex_<global index>`` and so are
    stable across slicings.
    """
    # Precompute JS-constructibility for every string pattern in one node call, so
    # the loop can separate not_js (out of scope) from transpiler errors.
    string_patterns = [r.get("pattern") for r in rows if isinstance(r.get("pattern"), str)]
    # Gate under the flags the harness will carry, not flagless: a `\p{...}` pattern
    # constructs unflagged (as literal escapes) but throws under the `/u` the
    # specializer applies, so a flagless gate would admit patterns that then
    # SyntaxError on every engine and get recorded `ok`.
    js_flags = [js_construction_flags(p) for p in string_patterns]
    js_results = classify_js(string_patterns, js_flags)
    js_by_pos = {}  # position-in-rows -> validity dict, for string-pattern rows only
    _pi = 0
    for pos, row in enumerate(rows):
        if isinstance(row.get("pattern"), str):
            js_by_pos[pos] = js_results[_pi]
            _pi += 1

    outcomes = []
    for pos, row in enumerate(rows):
        index = start + pos
        rid = paths.regex_id(index)
        pattern = row.get("pattern")
        if not isinstance(pattern, str):
            outcomes.append({"regex_id": rid, "index": index, "status": "skipped_non_regex",
                             "pattern": pattern})
            print(f"[{rid}] skipped_non_regex: pattern={pattern!r}")
            continue
        js = js_by_pos[pos]
        if not js["valid"]:
            outcomes.append({"regex_id": rid, "index": index, "status": "not_js",
                             "pattern": pattern, "js_error": js["error"]})
            print(f"[{rid}] not_js ({js['error']}): /{pattern}/")
            continue
        try:
            detail = _process_regex(index, pattern, config)
            if detail.pop("unsatisfiable", False):
                outcomes.append({"regex_id": rid, "index": index, "status": "unsatisfiable",
                                 "pattern": pattern, **detail})
                print(f"[{rid}] unsatisfiable (internal anchor matches nothing): /{pattern}/")
            elif detail["apis"] and all(a["num_strings"] == 0 for a in detail["apis"]):
                # Specialized, but zero strings on every API: contributes no cases,
                # and `ok` would count it as evaluated.
                outcomes.append({"regex_id": rid, "index": index, "status": "no_inputs",
                                 "pattern": pattern, **detail})
                print(f"[{rid}] no_inputs (0 strings generated on every API): /{pattern}/")
            else:
                outcomes.append({"regex_id": rid, "index": index, "status": "ok",
                                 "pattern": pattern, **detail})
                print(f"[{rid}] ok: /{pattern}/  ({detail['num_constraints']} base constraints)")
        except UnsupportedUnicodeProperty as e:  # typed: property not in the resolver
            outcomes.append({"regex_id": rid, "index": index,
                             "status": "unsupported_unicode_property",
                             "pattern": pattern, "property": e.token, "error": repr(e)})
            print(f"[{rid}] unsupported_unicode_property (\\p{{{e.token}}}): /{pattern}/")
        except SurrogateEscapeUnmodeled as e:  # typed: unmodeled UTF-16 surrogate
            outcomes.append({"regex_id": rid, "index": index,
                             "status": "surrogate_escape_unmodeled",
                             "pattern": pattern, "codepoint": e.codepoint, "error": repr(e)})
            print(f"[{rid}] surrogate_escape_unmodeled (U+{e.codepoint:04X}): /{pattern}/")
        except Exception as e:  # recorded as this regex's outcome, not swallowed
            outcomes.append({"regex_id": rid, "index": index, "status": "error",
                             "pattern": pattern, "error": repr(e),
                             "traceback": traceback.format_exc()})
            print(f"[{rid}] ERROR: /{pattern}/  {e!r}")
    return outcomes


def generate_all(config: Config, limit: int | None = None, start: int = 0) -> dict:
    """Run the generation pipeline over the corpus window ``[start, start+limit)``.

    ``start`` is the global corpus offset and ``limit`` the window size (default:
    to the end). Ids remain ``regex_<global index>``, so a windowed run produces
    exactly the artifacts and ids it would inside a full run.

    Writes ``results/run_record_<start>_<end>.json`` and returns it.
    """
    if start < 0:
        raise ValueError(f"start must be >= 0, got {start}")
    rows = load_corpus(config)
    end = None if limit is None else start + limit
    rows = rows[start:end]

    # The window is generated in one go, so it is its own chunk. Recorded with the
    # actual row count, since `limit=None` has no declared size.
    if rows:
        set_chunk_context(start, len(rows))

    outcomes = process_row_range(rows, start, config)

    counts = {}
    for o in outcomes:
        counts[o["status"]] = counts.get(o["status"], 0) + 1

    record = {"provenance": provenance(config), "start": start, "limit": limit,
              "counts": counts, "outcomes": outcomes}
    paths.ensure_results_dirs()
    # Named for its window so a later one cannot overwrite it, and written
    # atomically so a kill mid-write cannot leave a half record.
    record_path = paths.run_record_path(start, end)
    tmp = record_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(record, f, indent=2)
    os.replace(tmp, record_path)
    print(f"\nGeneration summary: {counts}  ->  {record_path}")
    return record
