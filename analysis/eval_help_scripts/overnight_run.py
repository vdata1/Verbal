"""One chunk of the overnight generation-correctness run.

Processes GLOBAL corpus indices ``[start, start+count)`` in a FRESH process (so
memory resets between chunks -- the long-lived single process bloats RSS and its
per-regex time roughly doubles across a few hundred regexes; a fresh process per
chunk keeps both bounded). Writes one self-contained record to
``<outdir>/chunk_<start:06d>.json`` ONLY on success, so a crashed/killed chunk
leaves no file and is simply retried on the next driver invocation (resume).

Uniform: uses the SAME ``process_row_range`` the single-process ``generate_all``
uses, with the chunk's global offset -- so chunked and single-process runs give
identical per-regex outcomes. No per-instance logic.

Usage:  python analysis/eval_help_scripts/overnight_run.py \
            --config config/overnight.yaml --start 0 --count 100 --outdir results/overnight
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from pipeline.config import (  # noqa: E402
    load_config, seed_everything, provenance, set_chunk_context,
)
from pipeline.run import load_corpus, process_row_range  # noqa: E402
import paths  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Process one corpus chunk (fresh process).")
    ap.add_argument("--config", required=True)
    ap.add_argument("--start", type=int, required=True, help="global corpus start index")
    ap.add_argument("--count", type=int, required=True, help="number of rows in this chunk")
    ap.add_argument("--outdir", required=True, help="directory for chunk_<start>.json")
    args = ap.parse_args()

    config = load_config(args.config)
    seed_everything(config)  # random.seed(config.seed); fuzz reseeds per call anyway
    # Declare this process's chunk so every artifact it writes records the --start /
    # --count that reproduce it, rather than relying on a reader to know the driver's
    # CHUNK=100 default (EXPERIMENT_GAPS G6 remaining item 2). Set before any artifact
    # is written, i.e. before process_row_range.
    set_chunk_context(args.start, args.count)
    paths.ensure_results_dirs()

    rows = load_corpus(config)
    chunk = rows[args.start:args.start + args.count]
    if not chunk:
        print(f"[chunk {args.start}] empty (start beyond corpus of {len(rows)}), nothing to do")
        return

    outcomes = process_row_range(chunk, args.start, config)

    counts = {}
    for o in outcomes:
        counts[o["status"]] = counts.get(o["status"], 0) + 1

    record = {
        "provenance": provenance(config),
        "start": args.start, "count": args.count, "actual": len(chunk),
        "counts": counts, "outcomes": outcomes,
    }
    os.makedirs(args.outdir, exist_ok=True)
    out_path = os.path.join(args.outdir, f"chunk_{args.start:06d}.json")
    # Write atomically (tmp + rename) so a crash mid-write never leaves a half file
    # that would be mistaken for a completed chunk on resume.
    #
    # The tmp name carries the PID: two processes covering the SAME chunk index (a
    # driver relaunched on top of a live one, or two overlapping windows into one
    # OUTDIR) would otherwise both open the one shared `chunk_XXXXXX.json.tmp` with
    # "w". Each truncates and writes from offset 0 with its own file offset, so the
    # shorter record lands over the front of the longer one and the longer one's tail
    # survives past its end -- the rename then publishes a chunk that reads as
    # "Extra data" to json.load. Per-PID tmp files make the writes disjoint, and the
    # rename picks a whole record as the winner.
    tmp_path = f"{out_path}.{os.getpid()}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(record, f, indent=2)
    os.replace(tmp_path, out_path)
    print(f"[chunk {args.start}] done: {counts} -> {out_path}")


if __name__ == "__main__":
    main()
