#!/usr/bin/env python3
r"""Bundle a run's ReDoS slice -- nominations, verdicts, harnesses -- into one folder.

WHY THIS EXISTS
---------------
``collect_discrepancies.py`` is the *value*-discrepancy collector: it walks
``eval_headline_<window>.json`` -> ``discrepancies[]`` and ships the diverging cells.
It never opens a ReDoS artifact. So a bundle produced by it is silently missing the
entire timing side of the run, which lives in files it does not name:

    redos_queue_<window>.json          nominations, taken UNDER LOAD  (REDOS_DEFER=1)
    redos_<window>.json                verdicts, re-measured SERIALLY (the confirm)
    redos_<window>.json.ratio_split.json   offline reclassification, if it was backfilled

This is the other half. Same contract as its sibling: it READS ONLY -- nothing in the
results tree is modified, moved or deleted -- so it is safe to run against a tree you
care about, and safe to run twice.

NOMINATIONS ARE NOT FINDINGS, AND THE BUNDLE KEEPS THEM APART
-------------------------------------------------------------
A queue entry is a timing taken while N workers saturated the box; the inflation factor
is unknown. Only ``eval/confirm_redos.py``, run serially on a quiet box, turns one into
a verdict. The bundle therefore labels every window with a ``kind``:

    confirmed   redos_<window>.json exists          -> verdict rows, usable evidence
    deferred    only redos_queue_<window>.json      -> NOT results yet; confirm still owed
    both        queue plus its confirm

Ship a deferred window anyway: the queue embeds ``harness_source``, so it is
self-contained and the confirm can be run on the receiving end instead. That is often
the right split of labour -- the confirm needs a quiet box, not the original one.

NO CLASSIFICATION HAPPENS HERE
------------------------------
Whether a row's gap is ``engine_specific_measured`` vs ``..._lower_bound`` is defined in
ONE place (``src/redos_ratio.py``) precisely so it cannot drift between call sites. This
collector re-implements none of it: it tallies the fields the artifact already carries,
and records ``split_fields_present: false`` when the artifact predates the split so the
receiving end knows to run ``backfill_ratio_split.py`` rather than reading the bare
``engine_specific`` count as a finding count.

WHAT LANDS IN THE OUTPUT
------------------------
    MANIFEST.json     windows, kinds, engine versions, provenance, counts, misses
    redos_<window>.json                     copied verbatim, when present
    redos_queue_<window>.json               copied verbatim, when present
    redos_<window>.json.ratio_split.json    copied verbatim, when present
    rows.jsonl        one object per confirmed row: the verdict, the input string that
                      produced it, and the path to the harness
    by_regex.json     rows folded to (regex_id, api) with the worst serial time, so the
                      reader sees ~5 patterns instead of ~800 rows
    harnesses/        the exact .js executed, by regex_id (confirm rows only -- queue
                      entries already carry their source inline)
    README.txt        how to process the bundle on the other end

Usage:
    python3 collect_redos.py --results <results> --out <dir>
    python3 collect_redos.py --results <results> --out <dir> --window 25000_28050
    python3 collect_redos.py --results <results> --out <dir> --per-regex 5
    python3 collect_redos.py --results <results> --out <dir> --strip-queue-source
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

# paths.redos_report_path() / redos_queue_path() write exactly these two names. Matched
# strictly for the same reason the sibling collector matches its headline strictly: a
# hand-renamed partial must never be picked up as if it were the current artifact.
_REPORT_RE = re.compile(r"^redos_(\d+)_(\d+)\.json$")
_QUEUE_RE = re.compile(r"^redos_queue_(\d+)_(\d+)\.json$")

TOOL_VERSION = "1.0"

# Fields written by src/redos_ratio.ratio_fields(). Their ABSENCE dates the artifact to
# before the measured/lower-bound split, which is the difference between "477 findings"
# and "59 measured, 418 censored" -- see redos_nomination/TRIAGE_CONFIRM_2026-08-07.md.
_SPLIT_FIELDS = ("engine_specific_measured", "engine_specific_lower_bound",
                 "ratio_censored")


def _flag_tag(flags: str) -> str:
    """Filename tag for a flag set. Mirrors paths.harness_flag_tag()."""
    return flags if flags else "none"


def _dump(obj) -> str:
    """JSON, ASCII-escaped -- NOT a stylistic choice.

    Corpus inputs contain lone surrogates on purpose (chaos_alphabet seeds them). Python
    holds them fine but cannot encode them to UTF-8, so ensure_ascii=False dies with
    UnicodeEncodeError partway through a bundle. Escaping to \\udXXX is lossless for any
    JSON reader.
    """
    return json.dumps(obj, ensure_ascii=True)


def _find_windows(results: str, want: list[str]) -> list[dict]:
    """[{tag, start, report, queue}] for the windows to collect, sorted by start row."""
    found: dict[str, dict] = {}
    for name in sorted(os.listdir(results)):
        for rx, key in ((_QUEUE_RE, "queue"), (_REPORT_RE, "report")):
            m = rx.match(name)
            if not m:
                continue
            tag = f"{m.group(1)}_{m.group(2)}"
            w = found.setdefault(tag, {"tag": tag, "start": int(m.group(1)),
                                       "report": None, "queue": None})
            w[key] = os.path.join(results, name)
            break
    # Filtered AFTER the scan, not during it, so the error below can name what is
    # actually on disk -- a typo'd window otherwise reports "present: (none)".
    missing = set(want) - set(found)
    if missing:
        raise SystemExit(
            f"no ReDoS artifact for window(s): {', '.join(sorted(missing))}\n"
            f"present in {results}: " + (", ".join(sorted(found)) or "(none)"))
    keep = [w for w in found.values() if not want or w["tag"] in want]
    return sorted(keep, key=lambda w: w["start"])


def _load_strings_index(path: str) -> dict:
    """{n: string-record} from an <api>.strings.jsonl, keyed by the record's own n.

    Keyed by the ``n`` FIELD, not by line position: the meta header occupies line 1, and
    relying on offset would silently shift every input by one.
    """
    index = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("kind") == "string":
                    index[rec["n"]] = rec
    except FileNotFoundError:
        pass
    return index


def _tally(rows: list) -> dict:
    """Count the classification fields the artifact ALREADY carries. See module docstring
    on why nothing is recomputed here."""
    t = {
        "confirmed": len(rows),
        "engine_specific": sum(1 for r in rows if r.get("engine_specific")),
        "timed_out_rows": sum(1 for r in rows if r.get("timed_out")),
        "is_lower_bound": sum(1 for r in rows if r.get("is_lower_bound")),
        "distinct_regexes": len({r["regex_id"] for r in rows}),
    }
    present = any(f in r for r in rows for f in _SPLIT_FIELDS)
    t["split_fields_present"] = present
    if present:
        for f in _SPLIT_FIELDS:
            t[f] = sum(1 for r in rows if r.get(f))
        t["unresolved_censored"] = sum(
            1 for r in rows if r.get("ratio_censored") and not r.get("engine_specific"))
    return t


def collect(results: str, out: str, windows: list[str], per_regex: int,
            strip_queue_source: bool) -> dict:
    wins = _find_windows(results, windows)
    os.makedirs(out, exist_ok=True)
    harness_root = os.path.join(out, "harnesses")
    os.makedirs(harness_root, exist_ok=True)

    manifest = {
        "tool": "collect_redos.py", "tool_version": TOOL_VERSION,
        "source_results": os.path.abspath(results),
        "per_regex_cap": per_regex or None,
        "queue_source_stripped": strip_queue_source,
        "windows": [],
        "totals": {"confirmed_rows": 0, "rows_written": 0, "queued_candidates": 0,
                   "harnesses_copied": 0, "regexes": 0},
        "misses": {"harness_missing": [], "strings_missing": []},
    }
    by_regex: dict[str, dict] = {}
    all_regexes: set[str] = set()
    written = 0

    with open(os.path.join(out, "rows.jsonl"), "w", encoding="utf-8") as rf:
        for w in wins:
            tag = w["tag"]
            entry = {"window": tag, "kind": None, "report": None, "queue": None}

            if w["queue"]:
                q = json.load(open(w["queue"], encoding="utf-8"))
                if strip_queue_source:
                    for e in q.get("queue", []):
                        if "harness_source" in e:
                            e["harness_source"] = None
                            e["harness_source_stripped"] = True
                    with open(os.path.join(out, os.path.basename(w["queue"])), "w",
                              encoding="utf-8") as f:
                        f.write(_dump(q))
                else:
                    shutil.copy2(w["queue"],
                                 os.path.join(out, os.path.basename(w["queue"])))
                entry["queue"] = {
                    "file": os.path.basename(w["queue"]),
                    "status": q.get("status"),
                    "candidates": q.get("candidates"),
                    "harnesses_missing": q.get("harnesses_missing"),
                    "slow_ms": q.get("slow_ms"), "engine_ratio": q.get("engine_ratio"),
                    "harness_timeout_s": q.get("harness_timeout_s"),
                    "engine_versions": q.get("engine_versions"),
                    "provenance": q.get("provenance"),
                    "self_contained": not strip_queue_source and any(
                        e.get("harness_source") for e in q.get("queue", [])),
                }
                manifest["totals"]["queued_candidates"] += q.get("candidates") or 0

            rows = []
            if w["report"]:
                rep = json.load(open(w["report"], encoding="utf-8"))
                shutil.copy2(w["report"],
                             os.path.join(out, os.path.basename(w["report"])))
                split = w["report"] + ".ratio_split.json"
                if os.path.exists(split):
                    shutil.copy2(split, os.path.join(out, os.path.basename(split)))
                rows = rep.get("confirmed", [])
                entry["report"] = {
                    "file": os.path.basename(w["report"]),
                    # An inline-confirm artifact has no `status` at all; only the
                    # deferred path writes "complete". Absent != incomplete, but it does
                    # mean the run was NOT the quiet-box confirm.
                    "status": rep.get("status", "(absent -- inline confirm)"),
                    "confirmed_by": rep.get("confirmed_by", "run_eval (inline)"),
                    "candidates": rep.get("candidates"),
                    "load_artifacts": rep.get("load_artifacts"),
                    "unmeasured": rep.get("unmeasured"),
                    "confirm_elapsed_s": rep.get("confirm_elapsed_s"),
                    "confirm_box": rep.get("confirm_box"),
                    "slow_ms": rep.get("slow_ms"),
                    "engine_ratio": rep.get("engine_ratio"),
                    "caveat": rep.get("caveat"),
                    "engine_versions": rep.get("engine_versions"),
                    "provenance": rep.get("provenance"),
                    "ratio_split_backfilled": os.path.exists(split),
                    "tally": _tally(rows),
                }
                manifest["totals"]["confirmed_rows"] += len(rows)

            entry["kind"] = ("both" if w["report"] and w["queue"]
                             else "confirmed" if w["report"] else "deferred")
            manifest["windows"].append(entry)
            print(f"  window {tag}: {entry['kind']} "
                  f"({len(rows)} confirmed rows, "
                  f"{(entry['queue'] or {}).get('candidates', 0)} queued)",
                  file=sys.stderr)

            strings_cache: dict[tuple[str, str], dict] = {}
            shipped: dict[str, int] = {}
            for r in rows:
                rid, api = r["regex_id"], r["api"]
                n, flags = r["n"], r["flags"]
                all_regexes.add(rid)

                serial = r.get("serial_ms") or {}
                worst = max(serial.values()) if serial else None
                agg = by_regex.setdefault(f"{rid}|{api}", {
                    "regex_id": rid, "api": api, "window": tag,
                    "pattern": r.get("pattern"), "rows": 0,
                    "worst_serial_ms": worst, "worst_row": {"n": n, "flags": flags},
                    "engines_timed_out": set(), "engine_specific_rows": 0,
                })
                agg["rows"] += 1
                agg["engines_timed_out"].update(r.get("timed_out") or [])
                agg["engine_specific_rows"] += 1 if r.get("engine_specific") else 0
                if worst is not None and (agg["worst_serial_ms"] is None
                                          or worst > agg["worst_serial_ms"]):
                    agg["worst_serial_ms"] = worst
                    agg["worst_row"] = {"n": n, "flags": flags}

                # The cap bounds what is SHIPPED, never what is counted: by_regex above
                # and the manifest tally see every row.
                if per_regex and shipped.get(rid, 0) >= per_regex:
                    continue

                key = (rid, api)
                if key not in strings_cache:
                    spath = os.path.join(results, rid, f"{api}.strings.jsonl")
                    strings_cache[key] = _load_strings_index(spath)
                    if not strings_cache[key]:
                        manifest["misses"]["strings_missing"].append(f"{rid}/{api}")
                srec = strings_cache[key].get(n)

                harness_name = f"{api}__{n}__{_flag_tag(flags)}.js"
                src = os.path.join(results, rid, harness_name)
                rel = os.path.join("harnesses", rid, harness_name)
                if os.path.exists(src):
                    os.makedirs(os.path.join(harness_root, rid), exist_ok=True)
                    shutil.copy2(src, os.path.join(out, rel))
                    manifest["totals"]["harnesses_copied"] += 1
                else:
                    manifest["misses"]["harness_missing"].append(f"{rid}/{harness_name}")
                    rel = None

                out_row = dict(r)
                out_row.update({
                    "window": tag,
                    "harness": rel,
                    "input": (srec or {}).get("string"),
                    "input_origin": (srec or {}).get("origin"),
                    "input_mutation": (srec or {}).get("mutation"),
                    "input_py_re_matches": (srec or {}).get("py_re_matches"),
                })
                rf.write(_dump(out_row) + "\n")
                shipped[rid] = shipped.get(rid, 0) + 1
                written += 1

    manifest["totals"]["rows_written"] = written
    manifest["totals"]["regexes"] = len(all_regexes)
    for k in manifest["misses"]:
        manifest["misses"][k] = sorted(set(manifest["misses"][k]))

    folded = []
    for agg in by_regex.values():
        agg["engines_timed_out"] = sorted(agg["engines_timed_out"])
        folded.append(agg)
    folded.sort(key=lambda a: (-(a["worst_serial_ms"] or 0), a["regex_id"]))
    with open(os.path.join(out, "by_regex.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(folded, indent=2, ensure_ascii=True))
    with open(os.path.join(out, "MANIFEST.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(manifest, indent=2, ensure_ascii=True))
    _write_readme(out, manifest)
    return manifest


def _write_readme(out: str, manifest: dict) -> None:
    """README.txt, not .md -- the project gitignores *.md wholesale, so a README.md
    dropped in a bundle would be silently untracked by the very push it exists for."""
    lines = []
    for w in manifest["windows"]:
        q, r = w["queue"], w["report"]
        lines.append(f"  {w['window']:<14} {w['kind']:<10} "
                     f"queued={((q or {}).get('candidates') or 0):<6} "
                     f"confirmed={((r or {}).get('tally') or {}).get('confirmed', 0)}")
    t = manifest["totals"]
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as f:
        f.write(f"""Verbal ReDoS bundle
===================

Collected by collect_redos.py v{manifest['tool_version']} from
{manifest['source_results']}

Windows:
{chr(10).join(lines) or '  (none)'}

Confirmed rows:   {t['confirmed_rows']} ({t['rows_written']} shipped with input+harness)
Queued nominees:  {t['queued_candidates']}
Distinct regexes: {t['regexes']}
Harnesses copied: {t['harnesses_copied']}
Per-regex cap:    {manifest['per_regex_cap'] or 'none (all rows shipped)'}

CONTENTS
  MANIFEST.json   windows, kind, engine versions, provenance, tallies, misses.
                  START HERE, and read `kind` before reading any number below it.
  by_regex.json   confirmed rows folded to (regex_id, api) with the worst serial time.
                  A handful of patterns account for hundreds of rows.
  rows.jsonl      one object per shipped confirmed row: the verdict fields verbatim,
                  plus the input string that produced it and the harness path.
  redos_<window>.json         the verdict artifact, verbatim.
  redos_queue_<window>.json   the nominations, verbatim. Entries embed harness_source,
                              so a deferred window can be confirmed on the far end.
  harnesses/      the exact .js executed, as <regex_id>/<api>__<n>__<flags>.js

READ THIS BEFORE QUOTING ANY COUNT
  1. kind=deferred means NOTHING in that window is a result. Queue timings were taken
     under load, with an unknown inflation factor. Confirm serially on a quiet box:
         python3 eval/confirm_redos.py --queue redos_queue_<window>.json
  2. Use serial_ms, never pool_ms.
  3. `engine_specific` is NOT a finding count. A timed-out engine is scored at the
     harness budget, so ratio = budget / fastest and the gate collapses into a threshold
     on the FAST engine. If MANIFEST reports split_fields_present=false, run
     analysis/eval_help_scripts/backfill_ratio_split.py before reading it; if true, read
     engine_specific_measured (two-sided) apart from engine_specific_lower_bound.
  4. is_lower_bound=true means the row was killed while still backtracking: the true
     cost is worse than recorded.
  5. confirmed != ReDoS. These are unrelated fuzz strings at one length, so nothing here
     measured superlinear growth. Only a growing-length family separates an algorithmic
     class from a constant factor -- see redos_nomination/growth_family.py.
  6. node and deno are both V8 and agree within ~1.2x wherever both were measured;
     slowest_engine flipping between them is scheduling noise, not a differential.

  Strings are ASCII-escaped (\\udXXX): corpus inputs contain lone surrogates on purpose.
  json.loads restores them; re-encoding to UTF-8 will raise.

  ENGINE VERSIONS MATTER. Timings are only comparable at the versions in MANIFEST.json.
""")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default="results",
                    help="the results mount to read (default: results)")
    ap.add_argument("--out", required=True,
                    help="output directory for the bundle (created if absent)")
    ap.add_argument("--window", action="append", default=[], metavar="START_END",
                    help="collect only this window (repeatable). Default: every window "
                         "with a ReDoS artifact.")
    ap.add_argument("--per-regex", type=int, default=0, metavar="N",
                    help="ship at most N confirmed rows per regex_id (input + harness). "
                         "COUNTS stay exact. Default 0 = all.")
    ap.add_argument("--strip-queue-source", action="store_true",
                    help="drop the embedded harness_source from queue entries. Shrinks "
                         "a queue by ~3x, but the queue stops being self-contained -- "
                         "confirm_redos.py then needs the original results tree.")
    args = ap.parse_args()

    if not os.path.isdir(args.results):
        raise SystemExit(f"results directory not found: {args.results}")

    print(f"collecting ReDoS slice from {args.results} -> {args.out}", file=sys.stderr)
    m = collect(args.results, args.out, args.window, args.per_regex,
                args.strip_queue_source)

    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, _, fs in os.walk(args.out) for f in fs)
    t = m["totals"]
    print(f"\n  confirmed rows : {t['confirmed_rows']} ({t['rows_written']} shipped)",
          file=sys.stderr)
    print(f"  queued nominees: {t['queued_candidates']}", file=sys.stderr)
    print(f"  distinct regexes: {t['regexes']}", file=sys.stderr)
    print(f"  harnesses      : {t['harnesses_copied']}", file=sys.stderr)
    for k, v in m["misses"].items():
        if v:
            print(f"  MISSING {k:16}: {len(v)} (listed in MANIFEST.json)",
                  file=sys.stderr)
    deferred = [w["window"] for w in m["windows"] if w["kind"] == "deferred"]
    if deferred:
        print(f"\n  NOTE: {len(deferred)} window(s) are nominations only, not results: "
              f"{', '.join(deferred)}", file=sys.stderr)
    print(f"  bundle size    : {size / 1e6:.1f} MB", file=sys.stderr)
    if size > 100e6:
        print("\n  NOTE: >100 MB. --per-regex 5 caps the shipped rows; counts stay "
              "exact. --strip-queue-source cuts the queues further.", file=sys.stderr)
    print(f"\ndone: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
