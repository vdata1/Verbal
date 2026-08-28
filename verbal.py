#!/usr/bin/env python3
"""Entry point: differential-test JavaScript regex engines.

Two modes:

    python verbal.py --regex '(?:^x)*?y'        one regex, given on the command line
    python verbal.py --limit 5                  a window of the corpus in the config

Both run the same pipeline: build a Fandango grammar that generates matching
strings, specialize it per JS regex API, synthesize harnesses, execute them on
every configured engine, and diff the results.

Artifacts land under results/. See README.md for the layout.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "eval"))

from pipeline.config import load_config  # noqa: E402
import paths  # noqa: E402
from run_eval import run_eval  # noqa: E402

DEFAULT_CONFIG = os.path.join(_ROOT, "config", "minimal.yaml")

# Where --regex writes its one-row corpus. Under PROJECT_ROOT because Config
# resolves `corpus` relative to it, and under results/ because it is an output.
SINGLE_REGEX_CORPUS = os.path.join("results", "single_regex_corpus.json")


def _single_regex_config(config, pattern: str):
    """Write `pattern` as a one-row corpus and return a config pointing at it."""
    corpus_path = os.path.join(paths.PROJECT_ROOT, SINGLE_REGEX_CORPUS)
    os.makedirs(os.path.dirname(corpus_path), exist_ok=True)
    with open(corpus_path, "w") as f:
        json.dump([pattern], f)
    return dataclasses.replace(config, corpus=SINGLE_REGEX_CORPUS)


def _summarize(headline: dict) -> None:
    totals = headline.get("totals", {})
    print()
    print("=" * 60)
    print(f"window     {headline['window']['start']}..{headline['window']['end']}")
    print(f"complete   {headline['complete']}")
    for key in sorted(totals):
        print(f"{key:<25} {totals[key]}")
    discrepancies = headline.get("discrepancies", [])
    if discrepancies:
        print(f"\n{len(discrepancies)} value discrepancy/ies:")
        for d in discrepancies:
            tag = d["flags"] or "none"
            print(f"  {d['regex_id']} {d['api']} #{d['n']} [{tag}]"
                  f"  -> results/{d['regex_id']}/{d['api']}.diff.json")
    else:
        print("\nNo value discrepancies in this window.")
    print("=" * 60)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Differential-test JS regex engines on one regex or a corpus window.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--regex", metavar="PATTERN",
                     help="test this single pattern instead of the configured corpus")
    ap.add_argument("--start", type=int, default=0,
                    help="corpus offset of the window (default: 0)")
    ap.add_argument("--limit", type=int, default=None,
                    help="window size in rows (default: config eval_slice)")
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="config YAML (default: config/minimal.yaml)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4,
                    help="engine-execution threads (default: core count). Affects "
                         "wall-clock only, never results.")
    args = ap.parse_args()

    config = load_config(args.config)

    start, limit = args.start, args.limit
    if args.regex is not None:
        if args.start:
            ap.error("--start does not apply with --regex (the corpus is one row)")
        config = _single_regex_config(config, args.regex)
        start, limit = 0, 1

    headline = run_eval(config, generate=True, limit=limit, start=start,
                        workers=args.workers)
    _summarize(headline)


if __name__ == "__main__":
    main()
