"""Build a run record (the shape ``eval/run_eval.py --skip-generate`` consumes) from
a directory of overnight ``chunk_*.json`` files.

The overnight generation runner records per-regex outcomes in chunks; the chunk
``outcomes`` carry the EXACT same schema as a ``run_record.json`` outcome (regex_id,
index, status, pattern, apis, ...). So this adapter is a concat + de-dup
(last-write-wins per regex_id) -- the SAME merge :mod:`overnight_aggregate` does --
and nothing else. No generation, no engine execution happens here; it is the seam
that lets a chunked HEAD regeneration feed the parallel differential eval.

Written atomically (tmp+rename) so a crash can't leave a half run_record that the
eval would then read as truth.

The record is named for the window the chunks cover
(``results/run_record_<start>_<end>.json``), so merging one range never overwrites
another's record. Feed it to the eval with ``--record``.

Prints the record's path (and nothing else) to stdout so a driver can pass it
straight to ``run_eval --record``; the human summary goes to stderr.

Usage:  ./bin/python analysis/eval_help_scripts/chunks_to_run_record.py \
            --outdir results/overnight_head [--out PATH]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))

import paths  # noqa: E402


def load_chunk(path: str) -> dict:
    """Read one chunk file, naming it if it is not parseable.

    A bare ``json.load`` in the merge loop reports only a line/char offset, which
    says nothing about WHICH of a few hundred chunks is bad -- and the merge reads
    them all, so the traceback is the only clue a caller gets. A corrupt chunk is
    also cheap to fix (delete it; the driver regenerates it on the next resume,
    since resume keys on the file's existence), so the remedy belongs in the error.
    """
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        size = os.path.getsize(path)
        raise SystemExit(
            f"corrupt chunk {path}: {e}\n"
            f"  ({size} bytes on disk; the JSON document ends at char {e.pos})\n"
            f"  A chunk written by two processes at once (a driver relaunched over a\n"
            f"  live one, or two windows sharing an OUTDIR) reads as 'Extra data'.\n"
            f"  Fix: delete this file and rerun the SAME driver command -- resume skips\n"
            f"  completed chunks and regenerates only this one."
        ) from e


def build_run_record(outdir: str, out_path: str | None = None) -> dict:
    chunk_files = sorted(glob.glob(os.path.join(outdir, "chunk_*.json")))
    if not chunk_files:
        raise SystemExit(f"no chunk_*.json found in {outdir} -- nothing to convert")

    outcomes: list[dict] = []
    provenance = None
    for cf in chunk_files:
        rec = load_chunk(cf)
        # All chunks in a HEAD run share one provenance; keep the first seen.
        provenance = provenance or rec.get("provenance")
        outcomes.extend(rec["outcomes"])

    # De-dup by regex_id (a range re-run with different bounds -> last write wins),
    # then order by numeric id so the record is deterministic regardless of chunk
    # discovery order. Identical policy to overnight_aggregate.
    by_id = {o["regex_id"]: o for o in outcomes}
    outcomes = [by_id[k] for k in sorted(by_id, key=lambda r: int(r.split("_")[1]))]

    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o["status"]] = counts.get(o["status"], 0) + 1

    # The merged window is whatever the chunks actually covered; record it so the
    # file can be named for it and never collide with another window's record.
    indices = [o["index"] for o in outcomes if "index" in o]
    if not indices:
        raise SystemExit(f"chunks in {outdir} carry no outcome index -- cannot scope")
    win_lo, win_hi = min(indices), max(indices) + 1

    run_record = {
        "provenance": provenance,
        "start": win_lo,
        "limit": win_hi - win_lo,    # spans the merged window; may not be a first-N slice
        "counts": counts,
        "outcomes": outcomes,
        "source": "chunks_to_run_record",
        "source_outdir": outdir,
    }

    out_path = out_path or paths.run_record_path(win_lo, win_hi)
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(run_record, f, indent=2)
    os.replace(tmp, out_path)
    # Human summary on stderr, the path alone on stdout: the window is discovered from
    # the chunks (a time-boxed run may stop short of its target), so a caller cannot
    # predict the filename and must be able to capture it -- see scoped_run.sh.
    print(f"run_record: {len(outcomes)} outcomes {counts} -> {out_path}", file=sys.stderr)
    print(out_path)
    return run_record


def main() -> None:
    ap = argparse.ArgumentParser(description="Chunks -> run_record.json adapter.")
    ap.add_argument("--outdir", required=True, help="directory of chunk_*.json files")
    ap.add_argument("--out", default=None,
                    help="output path (default: results/run_record_<start>_<end>.json "
                         "for the window the chunks cover)")
    args = ap.parse_args()
    build_run_record(args.outdir, args.out)


if __name__ == "__main__":
    main()
