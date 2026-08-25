#!/usr/bin/env python3
r"""Bundle every discrepant harness + its evidence into one pushable folder.

WHY THIS EXISTS
---------------
A finished run leaves its evidence spread across three places: the headline says
WHICH cells diverged, ``<rid>/<api>.diff.json`` says WHAT each engine returned, and
``<rid>/<api>__<n>__<flags>.js`` is the file that was actually executed. None of that
is portable -- a results tree is tens of GB and mostly agreement. Whoever processes
the findings usually is not whoever ran the experiment, and the interesting subset is
tiny: in a recorded 1000-row window, 1652 discrepant cells came from 18 distinct
regexes, and the harnesses for all of them are a few MB.

So this collects exactly the divergent slice into a self-contained directory that can
be committed and pushed as-is. It READS ONLY -- nothing in the results tree is
modified, moved or deleted, so it is safe to run against a tree you care about, and
safe to run twice.

WHAT LANDS IN THE OUTPUT
------------------------
    MANIFEST.json     windows collected, engine versions, provenance, counts, misses
    evidence.jsonl    one JSON object per discrepant cell (the full diff case, the
                      input string that produced it, and the harness path)
    clusters.json     the same cells grouped by (regex_id, api, engine partition),
                      so the reader sees ~5 root causes instead of ~1600 cells
    harnesses/        the exact .js files that were executed, by regex_id
    eval_headline_<window>.json    copied verbatim; the provenance anchor
    README.txt        how to process the bundle on the other end

REPRODUCTION IS THE HARNESS, NOT A HAND-WRITTEN SNIPPET
-------------------------------------------------------
Copying the .js rather than synthesizing a minimal repro is deliberate. Under ``g``/
``y`` the harness runs a lastIndex preset battery, so a divergence can live at
``preset_2`` -- which a hand-written ``re.exec(s)`` does NOT reproduce, because that
runs from lastIndex 0 (see api_descriptors._LASTINDEX_PRESETS_JS, and reduce.py's
handling of the same trap). The shipped harness reproduces the recorded result by
construction, at the same engine versions. Minimization is a downstream step:
run reduce.py on the bundle after it lands.

SIZE
----
Harnesses are ~2 KB and a full case record is ~4 KB (p50), so a window with 9k
divergent cells is ~55 MB -- pushable, but mostly redundant, since discrepancy cells
are counted per (regex x string x flag x api) and one engine fact books hundreds.
``--per-cluster N`` keeps the first N cells of each cluster and is the knob to reach
for; the cluster counts stay exact either way, so nothing about the run's numbers is
misreported by capping what is shipped.

Usage:
    python3 collect_discrepancies.py --results <results> --out <dir>
    python3 collect_discrepancies.py --results <results> --out <dir> --per-cluster 3
    python3 collect_discrepancies.py --results <results> --out <dir> --window 20000_23000
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

# Written by paths.eval_headline_path() and nothing else. Matched strictly so a
# hand-renamed partial (eval_headline_<w>.partial_oom_28750.json -- these exist) is
# never picked up as if it were current: a superseded partial read as authoritative
# is a silently wrong bundle, and the whole point of the collection is fidelity.
_HEADLINE_RE = re.compile(r"^eval_headline_(\d+)_(\d+)\.json$")

TOOL_VERSION = "1.0"


def _flag_tag(flags: str) -> str:
    """Filename tag for a flag set. Mirrors paths.harness_flag_tag()."""
    return flags if flags else "none"


def _find_headlines(results: str, want: list[str]) -> list[tuple[str, str]]:
    """[(window_tag, path)] for the headlines to collect, sorted by start row."""
    found = []
    for name in os.listdir(results):
        m = _HEADLINE_RE.match(name)
        if not m:
            continue
        tag = f"{m.group(1)}_{m.group(2)}"
        if want and tag not in want:
            continue
        found.append((int(m.group(1)), tag, os.path.join(results, name)))
    missing = set(want) - {t for _, t, _ in found}
    if missing:
        raise SystemExit(
            f"no headline for window(s): {', '.join(sorted(missing))}\n"
            f"present in {results}: "
            + (", ".join(sorted(t for _, t, _ in found)) or "(none)")
        )
    return [(t, p) for _, t, p in sorted(found)]


def _partition(runs: dict) -> str:
    """Engine partition for a case: which engines agreed with which.

    ``node,deno|bun`` means the two V8 engines returned one value and bun another.
    This is the cluster axis that matters -- the same partition on the same (regex,
    api) is almost always one fact booked many times. Engines with no comparable
    value (defect / timeout) are parked in a trailing group so they never silently
    merge into an agreement set they were not part of.
    """
    by_value: dict[str, list[str]] = {}
    absent = []
    for engine, r in sorted(runs.items()):
        c = r.get("comparable")
        if c is None:
            absent.append(engine)
        else:
            by_value.setdefault(c, []).append(engine)
    groups = sorted(",".join(sorted(v)) for v in by_value.values())
    if absent:
        groups.append("!" + ",".join(sorted(absent)))
    return "|".join(groups)


def _truncate_runs(case: dict, cap: int) -> tuple[dict, bool]:
    """Copy a case, capping each engine's stdout/stderr at ``cap`` bytes.

    Only pathological output trips this (p95 stdout is ~450 bytes), but an engine
    that dumps MB of text on stderr would otherwise dominate the bundle. Truncation
    is RECORDED per stream rather than done silently -- a reader must be able to
    tell "the engine printed this" from "the collector cut it off".
    """
    out = json.loads(json.dumps(case))   # deep copy; case is plain JSON
    hit = False
    for r in out.get("runs", {}).values():
        for key in ("stdout", "stderr"):
            s = r.get(key)
            if isinstance(s, str) and len(s) > cap:
                r[key] = s[:cap]
                r[f"{key}_truncated_bytes"] = len(s) - cap
                hit = True
    return out, hit


def _dump(obj) -> str:
    """JSON, ASCII-escaped -- NOT a stylistic choice.

    Corpus inputs contain lone surrogates on purpose (chaos_alphabet seeds them, and
    `surrogate_escape_unmodeled` is a run-record status). Python holds them fine but
    cannot encode them to UTF-8, so writing with ensure_ascii=False dies with
    UnicodeEncodeError partway through a bundle. Escaping to \\udXXX is lossless for
    any JSON reader and keeps the artifacts pure ASCII, which git also prefers.
    """
    return json.dumps(obj, ensure_ascii=True)


def _load_strings_index(path: str) -> dict:
    """{n: string-record} from an <api>.strings.jsonl, keyed by the record's own n.

    Keyed by the ``n`` FIELD, not by line position: the meta header occupies line 1,
    and relying on offset would silently shift every input by one.
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


def collect(results: str, out: str, windows: list[str], per_cluster: int,
            stdout_cap: int, allow_incomplete: bool) -> dict:
    headlines = _find_headlines(results, windows)
    if not headlines:
        raise SystemExit(f"no eval_headline_<start>_<end>.json found in {results}")

    os.makedirs(out, exist_ok=True)
    harness_root = os.path.join(out, "harnesses")
    os.makedirs(harness_root, exist_ok=True)

    manifest = {
        "tool": "collect_discrepancies.py", "tool_version": TOOL_VERSION,
        "source_results": os.path.abspath(results),
        "per_cluster_cap": per_cluster or None,
        "stdout_cap_bytes": stdout_cap,
        "windows": [], "totals": {"cells_reported": 0, "cells_written": 0,
                                  "harnesses_copied": 0, "clusters": 0},
        "misses": {"harness_missing": [], "case_missing": [], "diff_missing": []},
    }
    clusters: dict[str, dict] = {}
    written = 0
    ev_path = os.path.join(out, "evidence.jsonl")

    with open(ev_path, "w", encoding="utf-8") as ev:
        for tag, hpath in headlines:
            head = json.load(open(hpath, encoding="utf-8"))
            if not head.get("complete", False) and not allow_incomplete:
                print(f"  SKIP window {tag}: complete=false "
                      f"({head['units_done']}/{head['units_total']} units). "
                      f"Pass --allow-incomplete to collect it anyway.", file=sys.stderr)
                continue
            shutil.copy2(hpath, os.path.join(out, os.path.basename(hpath)))

            disc = head.get("discrepancies", [])
            manifest["windows"].append({
                "window": tag, "complete": head.get("complete"),
                "engine_versions": head.get("engine_versions"),
                "provenance": head.get("provenance"),
                "totals": head.get("totals"),
                "discrepancy_cells": len(disc),
            })
            manifest["totals"]["cells_reported"] += len(disc)
            print(f"  window {tag}: {len(disc)} discrepant cells", file=sys.stderr)

            diff_cache: dict[tuple[str, str], dict | None] = {}
            strings_cache: dict[tuple[str, str], dict] = {}

            for entry in disc:
                rid, api = entry["regex_id"], entry["api"]
                n, flags = entry["n"], entry["flags"]
                key = (rid, api)

                if key not in diff_cache:
                    dpath = os.path.join(results, rid, f"{api}.diff.json")
                    try:
                        diff_cache[key] = json.load(open(dpath, encoding="utf-8"))
                    except (FileNotFoundError, json.JSONDecodeError):
                        diff_cache[key] = None
                        manifest["misses"]["diff_missing"].append(f"{rid}/{api}")
                diff = diff_cache[key]
                if diff is None:
                    continue

                case = next((c for c in diff["results"]
                             if c["n"] == n and c["flags"] == flags), None)
                if case is None:
                    manifest["misses"]["case_missing"].append(
                        f"{rid}/{api}#{n}[{_flag_tag(flags)}]")
                    continue

                part = _partition(case["runs"])
                ckey = f"{rid}|{api}|{part}"
                cl = clusters.setdefault(ckey, {
                    "regex_id": rid, "api": api, "engine_partition": part,
                    "window": tag, "pattern": diff.get("pattern"),
                    "cells": 0, "cells_shipped": 0,
                    "representative": {"n": n, "flags": flags},
                })
                cl["cells"] += 1
                if per_cluster and cl["cells_shipped"] >= per_cluster:
                    continue

                if key not in strings_cache:
                    strings_cache[key] = _load_strings_index(
                        os.path.join(results, rid, f"{api}.strings.jsonl"))
                srec = strings_cache[key].get(n)

                tag_ = _flag_tag(flags)
                harness_name = f"{api}__{n}__{tag_}.js"
                src = os.path.join(results, rid, harness_name)
                rel = os.path.join("harnesses", rid, harness_name)
                if os.path.exists(src):
                    os.makedirs(os.path.join(harness_root, rid), exist_ok=True)
                    shutil.copy2(src, os.path.join(out, rel))
                    manifest["totals"]["harnesses_copied"] += 1
                else:
                    manifest["misses"]["harness_missing"].append(f"{rid}/{harness_name}")
                    rel = None

                case_out, truncated = _truncate_runs(case, stdout_cap)
                ev.write(_dump({
                    "window": tag,
                    "regex_id": rid, "api": api, "n": n, "flags": flags,
                    "pattern": diff.get("pattern"),
                    "flag_variants": diff.get("flag_variants"),
                    "engine_partition": part,
                    "cluster": ckey,
                    "harness": rel,
                    "input": (srec or {}).get("string"),
                    "input_origin": (srec or {}).get("origin"),
                    "input_mutation": (srec or {}).get("mutation"),
                    "input_py_re_matches": (srec or {}).get("py_re_matches"),
                    "stdout_truncated": truncated,
                    "case": case_out,
                }) + "\n")
                cl["cells_shipped"] += 1
                written += 1

    manifest["totals"]["cells_written"] = written
    manifest["totals"]["clusters"] = len(clusters)
    for k in manifest["misses"]:
        manifest["misses"][k] = sorted(set(manifest["misses"][k]))

    with open(os.path.join(out, "clusters.json"), "w", encoding="utf-8") as f:
        json.dump(sorted(clusters.values(),
                         key=lambda c: (-c["cells"], c["regex_id"], c["api"])),
                  f, indent=2)
    with open(os.path.join(out, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    _write_readme(out, manifest)
    return manifest


def _write_readme(out: str, manifest: dict) -> None:
    """README.txt, not .md -- the project gitignores *.md wholesale, so a README.md
    dropped in a bundle would be silently untracked by the very push it exists for."""
    wins = ", ".join(w["window"] for w in manifest["windows"]) or "(none)"
    t = manifest["totals"]
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as f:
        f.write(f"""Verbal discrepancy bundle
=========================

Collected by collect_discrepancies.py v{manifest['tool_version']} from
{manifest['source_results']}

Windows:            {wins}
Discrepant cells:   {t['cells_reported']} reported, {t['cells_written']} shipped
Clusters:           {t['clusters']}
Harnesses copied:   {t['harnesses_copied']}
Per-cluster cap:    {manifest['per_cluster_cap'] or 'none (all cells shipped)'}

CONTENTS
  MANIFEST.json   windows, engine versions, provenance, counts, and any misses
  clusters.json   cells grouped by (regex_id, api, engine partition), biggest first.
                  START HERE -- one engine fact books hundreds of cells, so the
                  cluster count is much closer to a bug count than the cell count.
  evidence.jsonl  one object per shipped cell: the full diff case (per-engine exit,
                  timed_out, stdout/stderr, canonical, comparable), the input string
                  that produced it, and the path to the harness.
  harnesses/      the exact .js executed, as <regex_id>/<api>__<n>__<flags>.js
  eval_headline_<window>.json   copied verbatim; the provenance anchor.

REPRODUCING A CASE
  Run the harness with the matching engine. It reproduces the recorded result by
  construction -- do NOT hand-write a snippet from the pattern alone. Under g/y the
  harness sweeps a lastIndex preset battery, so a divergence at preset_k does not
  reproduce from a bare call, which starts at lastIndex 0.

      node harnesses/<regex_id>/<api>__<n>__<flags>.js
      bun  harnesses/<regex_id>/<api>__<n>__<flags>.js
      deno run --quiet harnesses/<regex_id>/<api>__<n>__<flags>.js

  ENGINE VERSIONS MATTER. Results are only comparable at the versions recorded in
  MANIFEST.json; different node/bun/deno versions legitimately produce different
  artifacts. Check before concluding anything about a mismatch.
""" + _README_BODY)


# Kept out of the f-string above: it contains braces, which an f-string would try to
# interpolate (and did, until the first run of this script failed on it).
_README_BODY = r"""
READING IT
  python3 - <<'EOF'
  import json
  for line in open('evidence.jsonl'):
      e = json.loads(line)
      print(e['regex_id'], e['api'], '#%d' % e['n'],
            '[%s]' % (e['flags'] or 'none'), e['engine_partition'])
  EOF

  Strings are ASCII-escaped (\udXXX): corpus inputs contain lone surrogates on
  purpose. json.loads restores them; re-encoding to UTF-8 will raise.

CAVEATS
  - Cell counts are not bug counts. clusters.json is the honest view, and even it
    reports one bug once per corpus witness; reduce.py collapses further.
  - node and deno are both V8, so a node,deno|bun partition is one implementation
    disagreeing with one other, not a 2-vs-1 majority.
  - A partition with a leading '!' group (e.g. "node,deno|!bun") means that engine
    produced no comparable value at all -- a defect or a timeout, not a differing
    value. Check `case.runs.<engine>.timed_out` before calling it a discrepancy.
"""


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default="results",
                    help="the results mount to read (default: results)")
    ap.add_argument("--out", required=True,
                    help="output directory for the bundle (created if absent)")
    ap.add_argument("--window", action="append", default=[], metavar="START_END",
                    help="collect only this window (repeatable). Default: all "
                         "complete windows found.")
    ap.add_argument("--per-cluster", type=int, default=0, metavar="N",
                    help="ship at most N cells per (regex, api, engine partition) "
                         "cluster. Cluster COUNTS stay exact. Default 0 = all.")
    ap.add_argument("--max-stdout", type=int, default=8192, metavar="BYTES",
                    help="cap each engine's stdout/stderr in evidence.jsonl "
                         "(default 8192; truncation is recorded, never silent)")
    ap.add_argument("--allow-incomplete", action="store_true",
                    help="also collect windows whose headline says complete=false "
                         "(a killed run). Off by default.")
    args = ap.parse_args()

    if not os.path.isdir(args.results):
        raise SystemExit(f"results directory not found: {args.results}")

    print(f"collecting from {args.results} -> {args.out}", file=sys.stderr)
    m = collect(args.results, args.out, args.window, args.per_cluster,
                args.max_stdout, args.allow_incomplete)

    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, _, fs in os.walk(args.out) for f in fs)
    t = m["totals"]
    print(f"\n  cells reported : {t['cells_reported']}", file=sys.stderr)
    print(f"  cells shipped  : {t['cells_written']}", file=sys.stderr)
    print(f"  clusters       : {t['clusters']}", file=sys.stderr)
    print(f"  harnesses      : {t['harnesses_copied']}", file=sys.stderr)
    for k, v in m["misses"].items():
        if v:
            print(f"  MISSING {k:15}: {len(v)} (listed in MANIFEST.json)", file=sys.stderr)
    print(f"  bundle size    : {size / 1e6:.1f} MB", file=sys.stderr)
    if size > 100e6:
        print("\n  NOTE: >100 MB. Consider --per-cluster 3; cluster counts stay "
              "exact, only the shipped sample shrinks.", file=sys.stderr)
    print(f"\ndone: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
