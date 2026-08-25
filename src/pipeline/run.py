r"""Pipeline driver -- runs Stages 1-3 over a corpus slice, uniformly.

Reads the corpus (JSONL, one object per line with a ``pattern`` field), and for
each regex flows it through the SAME path: base spec -> specialize (per API) ->
generate strings + harnesses. There is no branching on regex id or API name.

Per-regex outcome policy (uniform classification, everything RECORDED, never a
silent skip -- CLAUDE.md):
- ``skipped_non_regex``  -- the corpus row's ``pattern`` is not a string (e.g.
  ``false``). It is not a regex; recorded and counted, not an error.
- ``not_js``             -- the pattern is not a constructible JS ``RegExp`` under the
  flags its harness will carry (the reference-engine gate in ``js_regex.py`` rejects it,
  validating a ``\p{...}``/``\u{...}`` pattern under ``/u`` -- EXPERIMENT_GAPS G1). Out
  of scope for a JS differential test; excluded cleanly, not counted as a bug.
- ``error``              -- the pattern IS a valid JS regex but Stage 1-3 raised
  (e.g. the transpiler can't parse a JS-only escape like ``\u{...}``). The
  exception (type, message, traceback) is recorded as this regex's first-class
  outcome and the sweep CONTINUES. This is not error-swallowing: each regex is an
  independent experimental unit and its failure is a recorded result -- exactly
  how the planned mis-compilation sweep finds latent bugs. Now that ``not_js`` is
  split off, ``error`` means specifically "a transpiler gap on a real JS regex".
- ``unsatisfiable``      -- Stage-1 analysis proves the regex matches nothing (an
  internal ``$``/``^`` pins a line boundary where a non-newline literal is required,
  typically an unexpanded ``$var`` template). There are no matching strings to
  generate, so we record it and stop after the base spec instead of emitting strings
  that can never match. A sound, conservative structural check (see ``regex_facts``).
- ``unsupported_unicode_property`` -- the pattern uses a ``\p{...}``/``\pX`` Unicode
  property the authoritative resolver (the ``regex`` module) does not know. Rather
  than silently mis-compile it, we record the property name as a typed outcome. Every
  KNOWN property is rewritten to an exact explicit char set (see the transpiler).
- ``surrogate_escape_unmodeled`` -- the pattern contains a UTF-16 surrogate code
  point (U+D800..U+DFFF), e.g. the surrogate-pair astral idiom ``\uD807[\uDEE0-...]``.
  We do not model UTF-16 pairing; recorded as a typed outcome rather than crashing on
  the un-encodable lone surrogate.
- ``no_inputs``          -- all APIs specialized but the fuzzer generated ZERO test
  strings on every one (typically a huge char class with unbounded repetition that
  exhausts ``fuzz_timeout_s``). It produces no cases; kept distinct from ``ok`` so it
  is not counted as evaluated (EXPERIMENT_GAPS G2).
- ``ok``                 -- all APIs specialized and generated at least one input.

Malformed corpus JSON (a line that is not valid JSON at all) is genuinely bad data
and raises loudly -- that is not a per-regex outcome.
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
    """Load the corpus JSONL into a list of row dicts (order preserved).

    Raises (fail loud) on a line that is not valid JSON -- malformed data, not a
    per-regex outcome.
    """
    rows: list[dict] = []
    with open(config.corpus_path, "r") as f:
        for lineno, line in enumerate(f):
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

    If Stage-1 analysis proves the regex matches nothing (an internal ``$``/``^``
    that pins a line boundary where a non-newline literal is required, e.g. an
    unexpanded ``$var`` template), we stop after the base spec and report it as its
    own outcome rather than generating strings that can never match.
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
    """Run Stages 1-3 over ``rows`` whose GLOBAL corpus ids are ``start .. start+len-1``.

    This is the single per-regex processing loop shared by :func:`generate_all`
    (``start=0``, whole slice) and the chunked overnight runner (``start`` = chunk
    offset). Keeping ONE function guarantees every regex flows the exact same code
    path regardless of how the corpus is sliced -- a chunked run and a single-process
    run produce identical per-regex outcomes (CLAUDE.md: uniform treatment). The
    regex id is always ``regex_<global index>``, so ids are stable across chunkings.
    """
    # Precompute JS-constructibility for every string pattern in ONE node call, so
    # the loop can cleanly separate not_js (out of scope) from transpiler errors.
    string_patterns = [r.get("pattern") for r in rows if isinstance(r.get("pattern"), str)]
    # Gate each pattern under the flags its harness will carry, not flagless: a
    # `\p{...}` pattern constructs unflagged (as literal escapes) but the specializer
    # runs it under `/u`, where it throws -- so a flagless gate admits patterns that
    # then SyntaxError on every engine and get recorded `ok` (EXPERIMENT_GAPS G1).
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
                # Specialized fine but the fuzzer produced NO test string on any API
                # (typically a huge char class + unbounded repetition that hits
                # fuzz_timeout_s). It contributes zero cases; `ok` would count it as
                # tested and inflate regexes_evaluated (EXPERIMENT_GAPS G2).
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
    """Run the generation pipeline over a corpus WINDOW ``[start, start+limit)``.

    ``start`` is the global corpus offset (default 0) and ``limit`` the window size
    (default: to the end). The window is a general slice applied uniformly to every
    regex -- ids remain ``regex_<global index>`` via ``process_row_range(start=...)``,
    so a windowed run (e.g. only the new rows 3000..3999) produces exactly the same
    per-regex artifacts and ids it would inside a full run (CLAUDE.md: uniform
    treatment; the window is not a per-instance branch).

    Writes a run record to ``results/run_record.json`` and returns it.
    """
    if start < 0:
        raise ValueError(f"start must be >= 0, got {start}")
    rows = load_corpus(config)
    end = None if limit is None else start + limit
    rows = rows[start:end]

    # This process generates the whole window in one go, so the window IS its chunk --
    # record it, so an artifact from a single-process run is as self-describing as one
    # from the chunked driver (EXPERIMENT_GAPS G6 remaining item 2). Uses the ACTUAL
    # row count, since `limit=None` (to end of corpus) has no declared size.
    if rows:
        set_chunk_context(start, len(rows))

    outcomes = process_row_range(rows, start, config)

    counts = {}
    for o in outcomes:
        counts[o["status"]] = counts.get(o["status"], 0) + 1

    record = {"provenance": provenance(config), "start": start, "limit": limit,
              "counts": counts, "outcomes": outcomes}
    paths.ensure_results_dirs()
    # Named for the window it covers so a later chunk cannot overwrite it, and
    # written atomically so a kill mid-write can't leave a half record that
    # --skip-generate would read as truth (see paths.run_record_path).
    record_path = paths.run_record_path(start, end)
    tmp = record_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(record, f, indent=2)
    os.replace(tmp, record_path)
    print(f"\nGeneration summary: {counts}  ->  {record_path}")
    return record
