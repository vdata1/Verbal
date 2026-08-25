#!/usr/bin/env python3
r"""Re-read confirmed ReDoS artifacts and split `engine_specific` after the fact.

WHY THIS IS NOT A RE-RUN
------------------------
`engine_specific` merged two very different rows: a measured two-sided gap, and a row
whose slow engine hit the harness budget so the ratio has a constant numerator (see
`src/redos_ratio.py`). The split needs no engine time to recover -- `_assemble` already
writes `serial_ms` and `timed_out` per confirmed row, which is exactly the input the
classifier takes. So every window confirmed before the split can be reclassified offline,
including the 2026-08-07 run whose 477 flagged rows are 418 censored / 59 measured.

IT DOES NOT MUTATE THE ARTIFACTS
--------------------------------
Results carry run provenance and are treated as read-only; a sidecar
`<artifact>.ratio_split.json` is written instead (`--write`), or nothing at all by
default. Nothing downstream reads the sidecar yet -- it exists so a reader can cite the
corrected counts without re-deriving them.

FAITHFULNESS CHECK
------------------
The recomputed union MUST equal the `engine_specific` already on disk, row for row: the
split only partitions that flag, it never changes it. Any mismatch means the artifact was
produced by different logic than `redos_ratio.ratio_fields` (a threshold change, a hand
edit, a schema drift) and the recomputation cannot be trusted for it. Mismatches are
reported per row and make the run exit non-zero rather than being written out.

Usage:
    python analysis/eval_help_scripts/backfill_ratio_split.py \
        /scratch/turcotte/verbal/results/redos_*.json [--write]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from redos_ratio import ratio_fields, summarize  # noqa: E402


def _reclassify(rows: list, engine_ratio: float) -> tuple[list, list]:
    """``(rows with the split fields added, mismatches)``.

    A row missing `serial_ms` is skipped rather than guessed at; it is reported as a
    mismatch so it cannot silently vanish from the counts.
    """
    out, bad = [], []
    for r in rows:
        ms = r.get("serial_ms") or {}
        if not ms:
            bad.append((r, "no serial_ms"))
            continue
        rf = ratio_fields(ms, r.get("timed_out") or [], engine_ratio)
        if rf["engine_specific"] != r.get("engine_specific"):
            bad.append((r, f"union {r.get('engine_specific')} on disk, "
                           f"{rf['engine_specific']} recomputed"))
            continue
        out.append({**r, **rf})
    return out, bad


def _label(row: dict) -> str:
    return (f"{row.get('regex_id')} {row.get('api')} #{row.get('n')} "
            f"[{row.get('flags') or 'none'}]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifacts", nargs="+")
    ap.add_argument("--write", action="store_true",
                    help="write <artifact>.ratio_split.json sidecars")
    ap.add_argument("--engine-ratio", type=float, default=None,
                    help="only for artifacts that do not record their own")
    args = ap.parse_args()

    total, failed = {}, False
    for path in args.artifacts:
        with open(path) as fh:
            art = json.load(fh)
        ratio = art.get("engine_ratio", args.engine_ratio)
        if ratio is None:
            print(f"!! {path}: no engine_ratio recorded and none passed -- SKIPPED",
                  file=sys.stderr)
            failed = True
            continue

        rows, bad = _reclassify(art.get("confirmed") or [], ratio)
        s = summarize(rows)
        win = art.get("window") or {}
        name = f"{win.get('start')}-{win.get('end')}" if win else os.path.basename(path)

        print(f"\n{name}  (engine_ratio {ratio}, {s['confirmed']} confirmed)")
        print(f"    engine_specific (union, as previously reported): {s['engine_specific']}")
        print(f"      measured, two-sided ................ {s['engine_specific_measured']}")
        print(f"      lower bound only (slow side cut off) {s['engine_specific_lower_bound']}")
        print(f"    unresolved: censored, under the gate . {s['unresolved_censored']}")
        if bad:
            failed = True
            print(f"    !! {len(bad)} row(s) could not be reclassified:", file=sys.stderr)
            for r, why in bad[:10]:
                print(f"       {_label(r)}: {why}", file=sys.stderr)
            if len(bad) > 10:
                print(f"       ... and {len(bad) - 10} more", file=sys.stderr)

        for k, v in s.items():
            total[k] = total.get(k, 0) + v

        if args.write and not bad:
            side = f"{path}.ratio_split.json"
            with open(side, "w") as fh:
                json.dump({"source": path, "window": art.get("window"),
                           "engine_ratio": ratio, "counts": s,
                           "confirmed": rows}, fh, indent=2)
            print(f"    -> {side}")
        elif args.write and bad:
            print("    (sidecar NOT written -- reclassification did not verify)",
                  file=sys.stderr)

    if len(args.artifacts) > 1:
        print(f"\n=== all {len(args.artifacts)} artifacts ===")
        for k, v in total.items():
            print(f"    {k}: {v}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
