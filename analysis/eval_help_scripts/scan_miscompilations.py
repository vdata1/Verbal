"""Generation-correctness scan over a corpus slice.

Runs the generation pipeline (Stages 1-3, NO engine diff) over the configured
corpus slice, then uses the built-in ``py_re_matches`` neutral oracle already
recorded in each ``<api>.strings.jsonl`` to flag miscompilations: a generated
string whose own regex matches it 0 times (``py_re_matches == 0``) did not come
from a faithful grammar -- the transpiler mis-modeled the regex.

This mirrors the 2026-07-07 full-sample scan, just at a larger, config-driven
slice. It is uniform: every regex/API flows through the same code path, and the
oracle is applied identically to every string. Nothing is skipped or special-cased.

Usage:  python analysis/eval_help_scripts/scan_miscompilations.py [--config PATH]
                                                                  [--skip-generate]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from pipeline.config import load_config  # noqa: E402
from pipeline.run import generate_all  # noqa: E402
import paths  # noqa: E402


def scan(config, generate: bool) -> dict:
    if generate:
        run_record = generate_all(config, limit=config.eval_slice)
    else:
        # Records are per-window; this scan mirrors the generate branch above,
        # i.e. the first-N slice starting at row 0.
        with open(paths.run_record_path(0, config.eval_slice)) as f:
            run_record = json.load(f)

    outcomes = run_record["outcomes"]
    status_counts = run_record["counts"]

    total_strings = 0
    nonmatching = 0            # py_re_matches == 0 (miscompilation signal)
    chaos_skipped = 0          # excluded from the oracle -- see the loop below
    unmeasured = 0             # py_re_matches == null (oracle timed out; unknown)
    per_regex_bad: dict[str, dict] = {}

    for o in outcomes:
        if o["status"] != "ok":
            continue
        rid = o["regex_id"]
        for api_summary in o["apis"]:
            api = api_summary["api"]
            spath = paths.api_strings_path(rid, api)
            if not os.path.exists(spath):
                continue
            with open(spath) as f:
                for line in f:
                    rec = json.loads(line)
                    if rec.get("kind") != "string":
                        continue
                    # The oracle below reads "regex does not match its own string"
                    # as proof the transpiler mis-modeled the regex. That inference
                    # holds only for a string the GRAMMAR produced. A chaos mutant
                    # (EXPERIMENT_GAPS.md G7) is perturbed after generation and is
                    # meant to be able to leave the language, so scoring one here
                    # would report the feature working as a transpiler bug. Default
                    # "fuzz": artifacts generated before chaos existed have no
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

    # rank regexes by how many non-matching strings they produced
    ranked = sorted(per_regex_bad.items(), key=lambda kv: -kv[1]["bad"])

    print("\n" + "=" * 66)
    print(f"corpus:      {config.corpus}  (slice {config.eval_slice})")
    print(f"outcomes:    {status_counts}")
    print(f"strings:     {total_strings} grammar-generated "
          f"(+{chaos_skipped} chaos mutants, not scanned)")
    if unmeasured:
        print(f"UNMEASURED (oracle timed out, py_re_matches=null): {unmeasured} "
              f"-- excluded from the oracle below, NOT counted as non-matching")
    pct = (100.0 * nonmatching / total_strings) if total_strings else 0.0
    print(f"NON-MATCHING (py_re_matches==0): {nonmatching}  ({pct:.1f}%)")
    print(f"regexes producing >=1 non-matching string: {len(ranked)}")
    print("=" * 66)
    if ranked:
        print("\nworst regexes (by non-matching string count):")
        for rid, info in ranked[:40]:
            apis = ",".join(sorted(info["apis"]))
            print(f"  {rid:>11}  bad={info['bad']:<4} [{apis}]  /{info['pattern']}/")

    # errors + unsatisfiable are separate correctness signals worth listing
    for status in ("error", "unsatisfiable", "not_js", "skipped_non_regex"):
        rows = [o for o in outcomes if o["status"] == status]
        if rows:
            print(f"\n{status} ({len(rows)}):")
            for o in rows[:40]:
                extra = o.get("error") or o.get("js_error") or ""
                print(f"  {o['regex_id']:>11}  /{o['pattern']}/  {str(extra)[:80]}")

    summary = {
        "corpus": config.corpus, "slice": config.eval_slice,
        "status_counts": status_counts, "total_strings": total_strings,
        "chaos_strings_excluded": chaos_skipped,
        "nonmatching": nonmatching, "nonmatching_pct": pct,
        "regexes_with_nonmatching": [
            {"regex_id": rid, "pattern": info["pattern"], "bad": info["bad"],
             "apis": sorted(info["apis"])}
            for rid, info in ranked
        ],
    }
    out_path = os.path.join(paths.RESULTS_DIR, "miscompilation_scan.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nsummary -> {out_path}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Generation-correctness scan.")
    ap.add_argument("--config", default=None, help="path to a config YAML")
    ap.add_argument("--skip-generate", action="store_true",
                    help="reuse existing artifacts / run_record.json")
    args = ap.parse_args()
    config = load_config(args.config)
    scan(config, generate=not args.skip_generate)


if __name__ == "__main__":
    main()
