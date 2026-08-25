"""Aggregate all completed overnight chunks into one correctness summary.

Reads every ``<outdir>/chunk_*.json``, merges the per-regex outcomes, and applies
the SAME ``py_re_matches==0`` miscompilation oracle as ``scan_miscompilations.py``
(a generated string its own regex does NOT match = a transpiler miscompilation).
Safe to run at ANY time -- mid-run for partial progress, or at the end. Idempotent.

Writes ``<outdir>/summary.json`` and prints a headline. No generation happens here.

Usage:  python analysis/eval_help_scripts/overnight_aggregate.py --outdir results/overnight
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paths  # noqa: E402
# One loader for both readers of a chunk dir, so a corrupt chunk names itself and
# carries the same remedy whichever entry point trips over it first.
from chunks_to_run_record import load_chunk  # noqa: E402


def aggregate(outdir: str) -> dict:
    chunk_files = sorted(glob.glob(os.path.join(outdir, "chunk_*.json")))
    if not chunk_files:
        raise SystemExit(f"no chunk_*.json found in {outdir} -- nothing to aggregate")

    outcomes = []
    provenance = None
    covered = []
    for cf in chunk_files:
        rec = load_chunk(cf)
        provenance = provenance or rec.get("provenance")
        covered.append((rec.get("start"), rec.get("actual")))
        outcomes.extend(rec["outcomes"])

    # De-dup by regex_id in case a chunk range was ever re-run with different bounds
    # (last write wins). Keeps aggregation robust to manual reruns.
    by_id = {o["regex_id"]: o for o in outcomes}
    outcomes = [by_id[k] for k in sorted(by_id, key=lambda r: int(r.split("_")[1]))]

    status_counts = {}
    for o in outcomes:
        status_counts[o["status"]] = status_counts.get(o["status"], 0) + 1

    total_strings = 0
    nonmatching = 0
    chaos_skipped = 0          # excluded from the oracle -- see the loop below
    unmeasured = 0             # py_re_matches == null (oracle timed out; unknown)
    per_regex_bad: dict[str, dict] = {}
    for o in outcomes:
        if o["status"] != "ok":
            continue
        rid = o["regex_id"]
        for api_summary in o.get("apis", []):
            api = api_summary["api"]
            spath = paths.api_strings_path(rid, api)
            if not os.path.exists(spath):
                continue
            with open(spath) as f:
                for line in f:
                    rec = json.loads(line)
                    if rec.get("kind") != "string":
                        continue
                    # Chaos mutants are perturbed AFTER generation and are meant to
                    # be able to leave the regex's language (EXPERIMENT_GAPS.md G7),
                    # so the py_re_matches==0 miscompilation oracle does not apply
                    # to them -- it would score the feature working as a transpiler
                    # bug. Default "fuzz" for pre-chaos artifacts, which have no
                    # origin field and are all grammar-produced.
                    if rec.get("origin", "fuzz") != "fuzz":
                        chaos_skipped += 1
                        continue
                    # null = the neutral oracle timed out on this string (a nested
                    # quantifier backtracking), NOT "matches zero times". Scoring it
                    # as 0 would manufacture a miscompilation from a timeout, so it
                    # is counted and reported separately instead.
                    if rec.get("py_re_matches", 0) is None:
                        unmeasured += 1
                        continue
                    total_strings += 1
                    if rec.get("py_re_matches", 0) == 0:
                        nonmatching += 1
                        b = per_regex_bad.setdefault(
                            rid, {"pattern": o["pattern"], "bad": 0, "apis": set()})
                        b["bad"] += 1
                        b["apis"].add(api)

    ranked = sorted(per_regex_bad.items(), key=lambda kv: -kv[1]["bad"])
    pct = (100.0 * nonmatching / total_strings) if total_strings else 0.0
    n_regexes = len(outcomes)

    print("\n" + "=" * 68)
    print(f"chunks aggregated:   {len(chunk_files)}  (regexes covered: {n_regexes})")
    print(f"outcomes:            {status_counts}")
    print(f"strings:             {total_strings} grammar-generated "
          f"(+{chaos_skipped} chaos mutants, not scanned)")
    if unmeasured:
        print(f"UNMEASURED (oracle timed out, py_re_matches=null): {unmeasured} "
              f"-- excluded from the oracle below, NOT counted as non-matching")
    print(f"NON-MATCHING (py_re_matches==0): {nonmatching}  ({pct:.2f}%)")
    print(f"regexes w/ >=1 non-matching:     {len(ranked)}")
    print("=" * 68)
    if ranked:
        print("\nworst regexes (by non-matching string count):")
        for rid, info in ranked[:50]:
            apis = ",".join(sorted(info["apis"]))
            print(f"  {rid:>12}  bad={info['bad']:<4} [{apis}]  /{info['pattern'][:60]}/")

    for status in ("error", "unsatisfiable"):
        rows = [o for o in outcomes if o["status"] == status]
        if rows:
            print(f"\n{status} ({len(rows)}):")
            for o in rows[:60]:
                extra = o.get("error") or o.get("js_error") or ""
                print(f"  {o['regex_id']:>12}  /{o['pattern'][:45]}/  {str(extra)[:70]}")

    summary = {
        "provenance": provenance,
        "chunks": len(chunk_files),
        "regexes_covered": n_regexes,
        "coverage_ranges": covered,
        "status_counts": status_counts,
        "total_strings": total_strings,
        "nonmatching": nonmatching,
        "nonmatching_pct": pct,
        "regexes_with_nonmatching": [
            {"regex_id": rid, "pattern": info["pattern"], "bad": info["bad"],
             "apis": sorted(info["apis"])}
            for rid, info in ranked
        ],
        "errors": [{"regex_id": o["regex_id"], "pattern": o["pattern"], "error": o.get("error")}
                   for o in outcomes if o["status"] == "error"],
        "unsatisfiable": [{"regex_id": o["regex_id"], "pattern": o["pattern"]}
                          for o in outcomes if o["status"] == "unsatisfiable"],
    }
    # tmp+rename (the repo-wide artifact policy): several drivers covering disjoint
    # windows into one outdir each aggregate on finish, so this can be written
    # concurrently -- a plain truncating write can leave a torn summary.json. The
    # rename is atomic, so a reader always sees one complete summary (last finisher
    # wins, which is the one that saw every chunk).
    out_path = os.path.join(outdir, "summary.json")
    tmp = f"{out_path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(summary, f, indent=2)
    os.replace(tmp, out_path)
    print(f"\nsummary -> {out_path}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Aggregate overnight chunks.")
    ap.add_argument("--outdir", default="results/overnight")
    args = ap.parse_args()
    aggregate(args.outdir)


if __name__ == "__main__":
    main()
