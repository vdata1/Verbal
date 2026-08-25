"""Rebuild a run record for a corpus window from the generation artifacts on disk.

Companion to :mod:`chunks_to_run_record` (which merges ``chunk_*.json`` from the
overnight runner). This one is the recovery seam for a plain ``run_eval`` /
``generate_all`` run whose record is missing: :func:`pipeline.run.generate_all`
writes the record only AFTER its whole loop finishes, so a run killed during
generation leaves a full tree of valid ``results/regex_*/`` artifacts and no record
at all -- and without a record ``--skip-generate`` cannot evaluate them, which would
force an expensive regeneration of work that is already on disk.

Nothing here generates or executes anything; it only restates on-disk facts in the
record schema. Everything the eval needs is already in each
``<rid>/<api>.strings.jsonl`` meta line: ``run_eval._compute_api`` reads ``count`` and
``flag_variants`` from that file, and uses only ``regex_id``, ``pattern`` and each
``api`` name from the record (``flags`` is a fallback for a meta line without
``flag_variants``).

Status is inferred from the artifacts, mirroring ``pipeline.run._process_regex``:
  ok             -- one ``<api>.strings.jsonl`` per DESCRIPTORS entry
  unsatisfiable  -- returns early with ``apis: []``, so base.fan but no strings
  torn_artifact  -- an unparseable/0-byte meta line: generation was killed mid-write
                    for this regex, so its artifacts are NOT trustworthy and it is
                    excluded rather than evaluated as a partial API set
  not_js / error -- no directory was ever created, so nothing to rebuild (these are
                    never evaluated anyway; only ``ok`` rows are)

The rebuild is verifiable: point ``--verify-against`` at a known-good record for the
same window and it diffs the ok set, patterns and API lists.

Usage:  ./bin/python analysis/eval_help_scripts/artifacts_to_run_record.py \
            --start 4000 --end 6000 [--out PATH] [--verify-against RECORD]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))

import paths  # noqa: E402
from pipeline.api_descriptors import DESCRIPTORS  # noqa: E402

# Same order _process_regex appends them in, so a rebuilt record is byte-comparable
# to a generated one.
APIS = [d.api for d in DESCRIPTORS]


def _read_meta(rdir: str, api: str) -> dict | None:
    """The strings.jsonl meta line for one (regex, api), or None if absent.

    Raises ValueError if the file exists but its meta line is unreadable -- that is a
    torn artifact, which must not be silently treated as a missing API.
    """
    spath = os.path.join(rdir, f"{api}.strings.jsonl")
    if not os.path.exists(spath):
        return None
    try:
        with open(spath) as f:
            return json.loads(f.readline())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"{spath}: unreadable meta line ({e})") from e


def build_run_record(start: int, end: int) -> dict:
    outcomes: list[dict] = []
    for index in range(start, end):
        rid = paths.regex_id(index)
        rdir = paths.regex_dir(rid)
        if not os.path.isdir(rdir):
            continue  # not_js / error / skipped: no artifacts were ever written
        apis: list[dict] = []
        pattern, torn = None, None
        for api in APIS:
            try:
                meta = _read_meta(rdir, api)
            except ValueError as e:
                torn = str(e)
                break
            if meta is None:
                continue
            pattern = meta.get("pattern")
            apis.append({"api": meta["api"], "flags": meta.get("flags", ""),
                         "num_strings": meta.get("count", 0)})
        if torn is not None:
            outcomes.append({"regex_id": rid, "index": index, "status": "torn_artifact",
                             "pattern": pattern, "apis": [], "detail": torn})
        elif len(apis) == len(APIS):
            outcomes.append({"regex_id": rid, "index": index, "status": "ok",
                             "pattern": pattern, "apis": apis})
        else:
            outcomes.append({"regex_id": rid, "index": index, "status": "unsatisfiable",
                             "pattern": pattern, "apis": []})

    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o["status"]] = counts.get(o["status"], 0) + 1
    return {
        # No provenance block: this record restates on-disk artifacts and did not run
        # generation, so it must not claim a config/commit it cannot prove. Each
        # artifact carries its own provenance, and the eval stamps the diffs it writes.
        "start": start,
        "limit": end - start,
        "counts": counts,
        "outcomes": outcomes,
        "source": "artifacts_to_run_record",
    }


def verify(rebuilt: dict, truth_path: str) -> bool:
    """Diff a rebuilt record against a known-good one for the same window."""
    with open(truth_path) as f:
        truth = json.load(f)
    t_ok = {o["regex_id"]: o for o in truth["outcomes"] if o["status"] == "ok"}
    r_ok = {o["regex_id"]: o for o in rebuilt["outcomes"] if o["status"] == "ok"}
    same_set = set(t_ok) == set(r_ok)
    bad_pat = [r for r in t_ok if r in r_ok and t_ok[r]["pattern"] != r_ok[r]["pattern"]]
    bad_api = [r for r in t_ok if r in r_ok and
               [a["api"] for a in t_ok[r]["apis"]] != [a["api"] for a in r_ok[r]["apis"]]]
    print(f"verify vs {truth_path}", file=sys.stderr)
    print(f"  ok regexes: truth={len(t_ok)} rebuilt={len(r_ok)} set_equal={same_set}",
          file=sys.stderr)
    if not same_set:
        print(f"  only in truth:   {sorted(set(t_ok) - set(r_ok))[:10]}", file=sys.stderr)
        print(f"  only in rebuilt: {sorted(set(r_ok) - set(t_ok))[:10]}", file=sys.stderr)
    print(f"  pattern mismatches={len(bad_pat)} api-list mismatches={len(bad_api)}",
          file=sys.stderr)
    ok = same_set and not bad_pat and not bad_api
    print(f"  VERDICT: {'MATCH' if ok else 'MISMATCH'}", file=sys.stderr)
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description="Artifacts -> run record (recovery).")
    ap.add_argument("--start", type=int, required=True, help="window start (inclusive)")
    ap.add_argument("--end", type=int, required=True, help="window end (EXCLUSIVE)")
    ap.add_argument("--out", default=None,
                    help="output path (default: results/run_record_<start>_<end>.json)")
    ap.add_argument("--verify-against", default=None,
                    help="a known-good record for this window; diff against it and exit "
                         "nonzero on mismatch (does not write unless it matches)")
    args = ap.parse_args()
    if args.end <= args.start:
        raise SystemExit(f"--end must be > --start (got {args.start}, {args.end})")

    rec = build_run_record(args.start, args.end)
    print(f"rebuilt rows [{args.start}, {args.end}): {rec['counts']}", file=sys.stderr)

    if args.verify_against and not verify(rec, args.verify_against):
        raise SystemExit("rebuild does not match the reference record -- not writing")

    out_path = args.out or paths.run_record_path(args.start, args.end)
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rec, f, indent=2)
    os.replace(tmp, out_path)  # atomic: the eval must never read a half record
    print(f"run_record: {len(rec['outcomes'])} outcomes -> {out_path}", file=sys.stderr)
    print(out_path)


if __name__ == "__main__":
    main()
