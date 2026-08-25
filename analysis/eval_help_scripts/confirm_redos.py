#!/usr/bin/env python3
r"""Confirm a deferred ReDoS queue on a quiet box.

THE OTHER HALF OF `--redos-defer`
---------------------------------
`run_eval.py --redos-defer` NOMINATES candidates under pool load and writes
`results/redos_queue_<window>.json` instead of measuring them; the serial confirm phase
it skips was 40% of the 11050-12050 run. This is the consumer that was deliberately not
built at the time. It re-executes each queued candidate SERIALLY on an unloaded box and
emits the same `results/redos_<window>.json` schema the inline path always produced, so
`dedupe_headline.py` needs no change.

WHY IT IS SERIAL, AND WHY IT CHECKS THE LOAD
--------------------------------------------
The whole reason a nomination is not a finding is that pool load inflates every reading.
Confirming on a busy box reproduces exactly the error the deferral was meant to remove,
so this refuses to run above `--max-load` unless forced -- and when forced, it stamps
`box_loaded: true` into the artifact so a later reader cannot mistake it for a clean
measurement. Shard ACROSS boxes (`--shard i/N`); never parallelise within one, because
absolute milliseconds are box-dependent even though ratios are not.

ENGINE GATING
-------------
Nominating under bun 1.3.14 and confirming under 1.3.15 silently measures a different
program than the one that was flagged, so a version mismatch is fatal by default.

The queue carries each harness's SOURCE inline, so this needs no access to the results
tree that produced it -- it runs anywhere the three engines exist.

USAGE
-----
  confirm_redos.py --queue results/redos_queue_12050_15050.json \
                   --out   results/redos_12050_15050.json
  confirm_redos.py --queue Q.json --out part2.json --shard 2/4
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "eval"))

from run_eval import (                      # noqa: E402
    HARNESS_TIMEOUT_S, _effective_ms, engine_versions, run_engine,
)

HEARTBEAT_S = 60.0


def _box(label: str | None) -> dict:
    """Identity of the confirming machine -- absolute ms are only meaningful with it.

    `socket.gethostname()` inside a container is the CONTAINER ID, which is ephemeral and
    identifies nothing: two shards confirmed on the same physical host record different
    "hostnames", and the same host tomorrow records another. Since sharding across boxes
    is the point, the operator can name the box with `--box-label`; the container id is
    kept alongside rather than passed off as the machine.
    """
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = -1.0
    return {
        "box_label": label,                       # operator-supplied; None if not given
        "container_id": socket.gethostname(),     # ephemeral -- NOT the host
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "loadavg": [round(load1, 2), round(load5, 2), round(load15, 2)],
    }


def _run_candidate(cand: dict, engines: list[str], timeout_s: int) -> dict | None:
    """Execute one queued harness across engines, from its INLINE source.

    Returns a `case`-shaped dict (`{"runs": {...}}`) so `_effective_ms` -- the same
    scoring the inline confirm used, including scoring a timed-out engine at the harness
    budget as a lower bound -- applies unchanged. None if the queue carried no source.
    """
    source = cand.get("harness_source")
    if source is None:
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(source)
        path = fh.name
    try:
        return {"runs": {e: run_engine(e, path) for e in engines}}
    finally:
        os.unlink(path)



# --- static pre-filter ------------------------------------------------------------
# See analysis/redos_nomination/TRIAGE_12050_15050.md. Sound in the direction used:
# returning False must mean "provably cannot be superlinear", so a dropped candidate is
# always a true negative.
_CLASS_RE = re.compile(r"\[(?:[^\]\\]|\\.)*\]")
_QUANT_GROUP = re.compile(r"\)\s*(?:[*+]|\{\d+,\d*\})")
_ALT_UNDER_QUANT = re.compile(r"\((?:\?:)?[^()]*\|[^()]*\)\s*(?:[*+]|\{\d+,\d*\})")
_NESTED_QUANT = re.compile(r"\([^()]*(?:[*+]|\{\d+,\d*\})[^()]*\)\s*(?:[*+]|\{\d+,\d*\})")


def _count_unbounded(pattern: str) -> int:
    """Count `*`, `+` and `{n,}` that are real quantifiers (not escaped, not in a class)."""
    s = _CLASS_RE.sub("C", pattern or "")
    out, i = 0, 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c in "*+":
            out += 1
        elif c == "{" and re.match(r"\{\d+,\s*\}", s[i:]):
            out += 1
        i += 1
    return out


def can_backtrack(pattern: str) -> bool:
    """False only when superlinear backtracking is IMPOSSIBLE for this pattern."""
    s = _CLASS_RE.sub("C", pattern or "")
    if _NESTED_QUANT.search(s) or _ALT_UNDER_QUANT.search(s) or _QUANT_GROUP.search(s):
        return True
    return _count_unbounded(pattern or "") >= 2


def confirm(queue_doc: dict, shard: tuple[int, int] | None, slow_ms: float,
            engine_ratio: float, forced: bool, prefilter: bool = True) -> dict:
    engines = list(queue_doc["engines"])
    candidates = queue_doc["queue"]

    if shard is not None:
        i, n = shard
        # Strided, not contiguous: candidates arrive grouped by regex, and one regex can
        # dominate a queue (regex_11807 was all 561 of window 11050-12050's). A
        # contiguous split would hand one box every expensive case and the others none.
        candidates = candidates[i - 1::n]

    prefiltered = []
    if prefilter:
        keep = []
        for c in candidates:
            (keep if can_backtrack(c.get("pattern") or "") else prefiltered).append(c)
        candidates = keep

    result = {
        "candidates": len(candidates),
        "confirmed": [],
        "load_artifacts": 0,
        "unmeasured": 0,
        "throw_artifacts": 0,
        "no_harness": 0,
        "prefiltered": len(prefiltered),
        "prefiltered_regexes": sorted({c["regex_id"] for c in prefiltered}),
    }
    if prefiltered:
        print(f"  pre-filter: {len(prefiltered)} row(s) across "
              f"{len(result['prefiltered_regexes'])} regex(es) provably cannot backtrack "
              f"(<=1 unbounded quantifier, no quantified group) -> dropped unmeasured",
              flush=True)
    start_t = last_print = time.monotonic()

    for idx, cand in enumerate(candidates, 1):
        rid, api = cand["regex_id"], cand["api"]
        n, flags = cand["n"], cand["flags"]

        case = _run_candidate(cand, engines, HARNESS_TIMEOUT_S)
        if case is None:
            result["no_harness"] += 1
            print(f"  ? NO HARNESS {rid} {api} #{n} [{flags or 'none'}] -- queue carried "
                  f"no inline source; cannot confirm off-box", flush=True)
            continue

        ms, timed_out = _effective_ms(case)
        if time.monotonic() - last_print >= HEARTBEAT_S:
            print(f"  ... {idx}/{len(candidates)} re-executed, "
                  f"{len(result['confirmed'])} confirmed "
                  f"(elapsed {time.monotonic() - start_t:.0f}s)", flush=True)
            last_print = time.monotonic()

        if not ms:
            # DIVERGENCE FROM THE INLINE `_confirm_redos`, deliberate. "No engine reported
            # exec_ms and none timed out" has two very different causes, and the inline
            # path folds both into `unmeasured`:
            #
            #   (a) every engine RAN and threw -- the error envelope carries no exec_ms by
            #       design. A harness that throws returns instantly, so it cannot be slow,
            #       and a pool nomination on it was pure contention. Observed live:
            #       regex_13150 replaceAll [i] is a TypeError (replaceAll needs `g`) that
            #       the pool nominated because bun was starved past the 20s budget.
            #   (b) every engine produced NO envelope at all -- genuinely unmeasured, and
            #       worth a human's attention.
            #
            # Folding (a) into `unmeasured` makes a contention artifact look like a broken
            # measurement. They are counted apart here; `unmeasured` now means (b) only.
            ran_and_threw = all(
                r.get("canonical") is not None and r["canonical"].get("ok") is False
                for r in case["runs"].values()
            )
            if ran_and_threw:
                result["throw_artifacts"] += 1
                continue
            result["unmeasured"] += 1
            print(f"  ? UNMEASURED {rid} {api} #{n} [{flags or 'none'}] -- no engine "
                  f"produced a result envelope (pool saw ms={cand.get('observed_ms')} "
                  f"timeout={cand.get('observed_timeout')})", flush=True)
            last_print = time.monotonic()
            continue

        slowest, fastest = max(ms, key=ms.get), min(ms, key=ms.get)
        if ms[slowest] <= slow_ms:
            result["load_artifacts"] += 1
            continue

        # SUPERSEDED by eval/confirm_redos.py (a47b8a6); every artifact on disk records
        # `confirmed_by: eval/confirm_redos.py`. Left as-is deliberately, so this stays a
        # faithful record of the prototype that produced the earlier triage. The live
        # pair now splits this flag into measured vs censored-lower-bound via
        # src/redos_ratio.py -- do not copy the expression below into new code.
        ratio = (ms[slowest] / ms[fastest]) if ms[fastest] > 0 else None
        engine_specific = len(ms) > 1 and (ratio is None or ratio >= engine_ratio)
        result["confirmed"].append({
            "regex_id": rid, "api": api, "n": n, "flags": flags,
            "pattern": cand.get("pattern"),
            "pool_ms": cand.get("observed_ms"), "pool_timeout": cand.get("observed_timeout"),
            "serial_ms": ms, "timed_out": timed_out,
            "is_lower_bound": bool(timed_out),
            "slowest_engine": slowest, "fastest_engine": fastest,
            "ratio": ratio, "engine_specific": engine_specific,
        })
        tag = "ENGINE-SPECIFIC" if engine_specific else "uniformly slow"
        rs = "inf" if ratio is None else f"{ratio:.1f}x"
        bound = f" [>= bound; timed out: {','.join(timed_out)}]" if timed_out else ""
        print(f"  [{idx}/{len(candidates)}] CONFIRMED {tag} {rid} {api} #{n} "
              f"[{flags or 'none'}] {slowest}={ms[slowest]:.0f}ms "
              f"{fastest}={ms[fastest]:.0f}ms ({rs}){bound}", flush=True)
        last_print = time.monotonic()

    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shard", help="i/N -- confirm only shard i of N (strided)")
    ap.add_argument("--max-load", type=float, default=None,
                    help="refuse if 1-min loadavg exceeds this (default: cpu_count/4)")
    ap.add_argument("--force-loaded", action="store_true",
                    help="run anyway on a busy box; stamps box_loaded into the artifact")
    ap.add_argument("--box-label",
                    help="durable name for THIS machine (container hostnames are "
                         "ephemeral); recorded so shards can be attributed")
    ap.add_argument("--no-prefilter", action="store_true",
                    help="measure even patterns that provably cannot "
                         "backtrack (see TRIAGE_12050_15050.md)")
    ap.add_argument("--allow-engine-mismatch", action="store_true",
                    help="confirm even if engine versions differ from the nomination")
    args = ap.parse_args()

    with open(args.queue) as fh:
        q = json.load(fh)

    if q.get("status") != "deferred":
        print(f"[warn] queue status is {q.get('status')!r}, expected 'deferred'",
              file=sys.stderr)

    # --- engine gate ---------------------------------------------------------
    live = engine_versions(tuple(q["engines"]))
    nominated = q.get("engine_versions", {})
    mismatch = {e: (nominated.get(e), live.get(e))
                for e in q["engines"] if nominated.get(e) != live.get(e)}
    if mismatch:
        lines = "\n".join(f"    {e}: nominated {a!r}, this box {b!r}"
                          for e, (a, b) in mismatch.items())
        if not args.allow_engine_mismatch:
            sys.exit("ABORT: engine version mismatch -- confirming a different program "
                     f"than was nominated.\n{lines}\n"
                     "  Pin the engines to the nominated versions, or pass "
                     "--allow-engine-mismatch to record the confirmation as cross-version.")
        print(f"[warn] proceeding across engine versions:\n{lines}", file=sys.stderr)

    # --- load gate -----------------------------------------------------------
    box = _box(args.box_label)
    max_load = args.max_load if args.max_load is not None else (os.cpu_count() or 4) / 4.0
    loaded = box["loadavg"][0] > max_load
    if loaded and not args.force_loaded:
        sys.exit(f"ABORT: 1-min loadavg {box['loadavg'][0]} exceeds --max-load {max_load}.\n"
                 "  Confirming under load reproduces the exact error the deferral exists to\n"
                 "  remove: inflated timings that turn contention into a finding.\n"
                 "  Wait for the box to drain, or pass --force-loaded (recorded in the artifact).")

    shard = None
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        if not 1 <= i <= n:
            sys.exit(f"bad --shard {args.shard}")
        shard = (i, n)

    t0 = time.monotonic()
    res = confirm(q, shard, q["slow_ms"], q["engine_ratio"], args.force_loaded,
                  prefilter=not args.no_prefilter)
    elapsed = time.monotonic() - t0

    out = {
        # --- the schema dedupe_headline.py already reads, unchanged ----------
        "window": q["window"],
        "engine_versions": live,
        "provenance": q.get("provenance"),
        "slow_ms": q["slow_ms"],
        "engine_ratio": q["engine_ratio"],
        "caveat": ("confirmed = engine-specific slowness, NOT proven ReDoS: these are "
                   "unrelated fuzz strings, not one shape at growing lengths, so no "
                   "superlinear scaling was measured"),
        "candidates": res["candidates"],
        "confirmed": res["confirmed"],
        "load_artifacts": res["load_artifacts"],
        "unmeasured": res["unmeasured"],
        # --- additive: how and where this confirmation was produced ----------
        "confirmed_on": box,
        "box_loaded": bool(loaded),
        "engine_versions_nominated": nominated,
        "cross_version": bool(mismatch),
        "shard": ({"index": shard[0], "of": shard[1]} if shard else None),
        "queue_file": os.path.basename(args.queue),
        "queue_candidates_total": q.get("candidates"),
        "throw_artifacts": res["throw_artifacts"],
        "no_harness": res["no_harness"],
        "prefiltered": res["prefiltered"],
        "prefiltered_regexes": res["prefiltered_regexes"],
        "elapsed_s": round(elapsed, 1),
    }

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    es = sum(1 for c in res["confirmed"] if c["engine_specific"])
    print("=" * 60)
    print(f"candidates re-executed: {res['candidates']}")
    print(f"confirmed:              {len(res['confirmed'])}  ({es} engine-specific)")
    print(f"load artifacts:         {res['load_artifacts']}  [fast once unloaded]")
    print(f"unmeasured:             {res['unmeasured']}  [no envelope at all]")
    print(f"throw artifacts:        {res['throw_artifacts']}  "
          f"[harness throws instantly -> pool nomination was contention]")
    print(f"no harness in queue:    {res['no_harness']}")
    print(f"pre-filtered:           {res['prefiltered']}  [provably cannot backtrack; unmeasured by design]")
    print(f"elapsed:                {elapsed:.0f}s   -> {args.out}")
    if loaded:
        print("WARNING: box was loaded; artifact stamped box_loaded=true and the "
              "absolute milliseconds are NOT trustworthy.")


if __name__ == "__main__":
    main()
