"""eval/confirm_redos.py -- the consumer side of the ReDoS nominate/confirm split.

``run_eval.py --redos-defer`` nominates slow cases under pool load and writes them to
``results/redos_queue_<window>.json`` WITHOUT measuring them. This script is the other
half: it re-executes those nominations serially on a quiet box and emits a verdict
artifact in the SAME schema ``run_eval.py`` writes inline, so downstream consumers
read either one unchanged.

Why it is a separate program, and why it is deliberately slow:

- **Serial is the point, not a limitation.** A nomination is a reading taken while 32
  workers saturated the cores; it is inflated by an unknown factor. Only an unloaded
  re-run measures. Running the confirm itself in parallel would reintroduce exactly the
  contention that made the nomination untrustworthy. To go faster, shard the queue across
  BOXES (``--shard i/N``), never across cores of one box.
- **It runs off the INLINED harness source.** ``run_eval._diff_one`` re-executes
  ``results/<rid>/<api>__<n>__<flags>.js`` off disk, so a queue of bare pointers is only
  meaningful on the machine that generated it. Each queue entry carries its harness text,
  and this script materializes that text into a scratch tree mirroring the original
  layout. The queue file alone is sufficient input -- no results/ tree required.
- **Ratios travel; milliseconds do not.** ``engine_specific`` keys on
  slowest/fastest >= ``engine_ratio``, which survives a change of box; the absolute
  ``slow_ms`` floor and the harness budget do not. Both are taken FROM THE QUEUE rather
  than from a config file, so a confirm always applies the thresholds its nominations
  were made under.
- **...but only while both ends are measured.** Once the slow engine is censored at the
  budget the ratio has a constant numerator, and the gate turns into a threshold on the
  FAST engine's time. Such rows carry ``ratio_censored``; the flag is split into
  ``engine_specific_measured`` and ``engine_specific_lower_bound`` and must be reported
  that way. ``run_eval._ratio_fields`` owns this and is shared with the inline path.

Hard gates (refusals, not warnings):

- **Engine versions must match the queue's.** Nominating under bun 1.3.14 and confirming
  under 1.3.15 measures a different program than the one that was flagged. Override with
  ``--allow-engine-mismatch`` only when you intend to compare across versions, and know
  that the resulting artifact is no longer a confirm of that queue.
- **The queue must be a queue.** ``status: deferred`` is required, so a
  ``redos_<window>.json`` report (verdicts, already measured) can never be fed back in as
  if it were nominations.

Crash-safety: this is a multi-hour serial job, and the thing it is fixing is a run that
lost work by flushing only at the end. Every candidate's verdict is appended to
``results/redos_<window>.partial.json`` (atomic tmp+rename, rewritten every
``--checkpoint-every`` candidates), and ``--resume`` picks up from it. The final
``results/redos_<window>.json`` is written only on completion, so a partial can never be
mistaken for a finished report -- the same naming discipline the queue/report split uses.

Usage:
    python eval/confirm_redos.py --queue results/redos_queue_12050_15050.json [--resume]
    python eval/confirm_redos.py --queue A.json --queue B.json --resume
    python eval/confirm_redos.py --queue Q.json --shard 0/4      # this box does 1 of 4
    python eval/confirm_redos.py --merge results/redos_15050_20035.shard*.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import hashlib
import platform
import socket
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "eval"))

import run_eval  # noqa: E402  -- module object: HARNESS_TIMEOUT_S is rebound below
from run_eval import (  # noqa: E402
    _atomic_write_json, _effective_ms, _timed_out_engines, engine_versions, run_engine,
)

# Longest silence before a progress line. Inherited from run_eval's inline phase for the
# same reason: a stretch of load artifacts produces no verdict lines at all, and without
# a heartbeat that is indistinguishable from a hang.
HEARTBEAT_S = run_eval._CONFIRM_HEARTBEAT_S

_REPORT_CAVEAT = (
    "confirmed = engine-specific slowness, NOT proven ReDoS: these are unrelated fuzz "
    "strings, not one shape at growing lengths, so no superlinear scaling was measured"
)


def _box() -> dict:
    """Identify the machine that produced these measurements.

    Absolute milliseconds are only interpretable against the box that took them, and
    sharding means one window's verdicts can come from several. Recording this per
    artifact is what keeps a merged report honest.
    """
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = None
    try:
        affinity = sorted(os.sched_getaffinity(0))
        cpus = f"{len(affinity)} of {os.cpu_count()} (affinity {affinity[0]}-{affinity[-1]})"
    except AttributeError:
        cpus = str(os.cpu_count())
    return {
        # A stable per-machine tag rather than the hostname itself: merging shards only
        # needs to tell boxes apart, and the artifact should not carry machine names.
        "hostname": "box_" + hashlib.sha256(
            socket.gethostname().encode("utf-8")).hexdigest()[:8],
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpus": cpus,
        "loadavg_at_start": [load1, load5, load15],
    }


def _key(c: dict) -> str:
    """Stable identity of one candidate, for resume and dedup."""
    return f"{c['regex_id']}|{c['api']}|{c['n']}|{c['flags']}"


def _materialize(cand: dict, scratch: str) -> str | None:
    """Write a candidate's inlined harness to disk, mirroring the original layout.

    Returns the path, or None when the queue carried no source (``harnesses_missing``).
    The original tree shape is reproduced because the basename alone
    (``<api>__<n>__<flags>.js``) is NOT unique -- regex_id is the directory -- so a flat
    scratch dir would let one candidate's harness silently overwrite another's and every
    subsequent measurement would be of the wrong program.
    """
    src = cand.get("harness_source")
    if src is None:
        return None
    base = os.path.basename(cand.get("harness_path") or
                            f"{cand['api']}__{cand['n']}__{cand['flags'] or 'none'}.js")
    d = os.path.join(scratch, cand["regex_id"])
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, base)
    with open(path, "w") as fh:
        fh.write(src)
    return path


def _verdict(cand: dict, engines: list, scratch: str, slow_ms: float,
             engine_ratio: float) -> dict:
    """Re-execute ONE candidate on every engine and classify it.

    Mirrors ``run_eval._confirm_redos``'s per-candidate logic exactly -- including
    scoring a timed-out engine at the harness budget (a lower bound, never a
    measurement) and the ratio=null case where the fastest engine is unmeasurably fast.
    Divergence here would make deferred windows incomparable with inline ones, so the
    ranking/flagging step is not re-implemented: both paths call the same
    ``run_eval._ratio_fields``, which is also where the measured vs censored-lower-bound
    split is defined.
    """
    rid, api, n, flags = cand["regex_id"], cand["api"], cand["n"], cand["flags"]
    base = {"regex_id": rid, "api": api, "n": n, "flags": flags,
            "pattern": cand.get("pattern"),
            "pool_ms": cand.get("observed_ms"), "pool_timeout": cand.get("observed_timeout")}

    hpath = _materialize(cand, scratch)
    if hpath is None:
        # Queued as a pointer only. Counted as unmeasured rather than dropped: the
        # nominated count must reconcile with the verdict counts.
        return {**base, "verdict": "no_harness"}

    runs = {e: run_engine(e, hpath) for e in engines}
    case = {"runs": runs}
    ms, timed_out = _effective_ms(case)
    if not ms:
        return {**base, "verdict": "unmeasured",
                "exits": {e: r["exit"] for e, r in runs.items()}}

    rf = run_eval._ratio_fields(ms, timed_out, engine_ratio)
    if ms[rf["slowest_engine"]] <= slow_ms:
        # Fast once unloaded: the pool reading was contention, not the regex.
        return {**base, "verdict": "load_artifact", "serial_ms": ms}

    return {**base, "verdict": "confirmed",
            "serial_ms": ms, "timed_out": timed_out,
            "is_lower_bound": bool(timed_out),
            **rf}


def _es_summary(confirmed: list) -> str:
    """The engine-specific tally as one line, split rather than merged.

    A single count over ``engine_specific`` reads as that many measured differentials
    when most of it is usually rows whose slow engine ran out the clock (see
    ``run_eval._ratio_fields``). ``unresolved`` are censored rows that fell UNDER the
    gate -- not differentials, but not negatives either.
    """
    meas = sum(1 for c in confirmed if c.get("engine_specific_measured"))
    lb = sum(1 for c in confirmed if c.get("engine_specific_lower_bound"))
    unres = sum(1 for c in confirmed
                if c.get("ratio_censored") and not c.get("engine_specific"))
    return (f"engine-specific {meas} measured + {lb} lower-bound-only, "
            f"{unres} unresolved [censored under the gate]")


def _assemble(queue: dict, records: list, shard: tuple[int, int] | None,
              box: dict, elapsed: float, status: str) -> dict:
    """Build the redos_<window>.json artifact from accumulated verdicts.

    Emits ``run_eval``'s report schema verbatim -- ``confirmed`` carries only the
    confirmed entries, with ``load_artifacts``/``unmeasured`` as counts -- so a
    downstream consumer needs no change. The extra keys (``verdicts``,
    ``confirm_box``, ``shard``) are additive and read by key.
    """
    confirmed = [{k: v for k, v in r.items() if k != "verdict"}
                 for r in records if r["verdict"] == "confirmed"]
    try:
        load_now = list(os.getloadavg())
    except OSError:
        load_now = None
    return {
        "window": queue.get("window"),
        "engine_versions": queue.get("engine_versions"),
        "provenance": queue.get("provenance"),
        "slow_ms": queue.get("slow_ms"),
        "engine_ratio": queue.get("engine_ratio"),
        "caveat": _REPORT_CAVEAT,
        "candidates": queue.get("candidates"),
        "confirmed": confirmed,
        "load_artifacts": sum(1 for r in records if r["verdict"] == "load_artifact"),
        "unmeasured": sum(1 for r in records if r["verdict"] in ("unmeasured", "no_harness")),
        # --- additive: provenance of the CONFIRM, distinct from the nomination's ---
        "status": status,
        "confirmed_by": "eval/confirm_redos.py",
        "confirm_box": {**box, "loadavg_at_write": load_now},
        "confirm_elapsed_s": round(elapsed, 1),
        "shard": None if shard is None else {"index": shard[0], "of": shard[1]},
        "queue_source": queue.get("_source_path"),
        "harness_timeout_s": queue.get("harness_timeout_s"),
        "verdicts_total": len(records),
        # Full per-candidate record INCLUDING load artifacts. `confirmed` alone cannot
        # distinguish "re-ran fast" from "never ran", and that difference is the whole
        # value of the confirm pass.
        "verdicts": records,
    }


def _out_paths(queue_path: str, window: dict, shard) -> tuple[str, str]:
    """``(final, partial)`` output paths for a queue, honoring the shard suffix."""
    d = os.path.dirname(os.path.abspath(queue_path))
    tag = f"{window.get('start')}_{window.get('end')}"
    suffix = "" if shard is None else f".shard{shard[0]}of{shard[1]}"
    return (os.path.join(d, f"redos_{tag}{suffix}.json"),
            os.path.join(d, f"redos_{tag}{suffix}.partial.json"))


def confirm_queue(queue_path: str, shard, resume: bool, checkpoint_every: int,
                  allow_mismatch: bool, scratch_root: str) -> str:
    queue = json.load(open(queue_path))
    queue["_source_path"] = os.path.abspath(queue_path)

    if queue.get("status") != "deferred":
        raise SystemExit(
            f"REFUSING {queue_path}: status={queue.get('status')!r}, expected 'deferred'. "
            "This looks like a report (verdicts already measured), not a queue of "
            "nominations. Feeding a report back in would relabel measurements as if they "
            "had been re-confirmed.")

    engines = list(queue["engines"])
    want, have = queue.get("engine_versions") or {}, engine_versions(tuple(engines))
    if want != have:
        msg = (f"engine version mismatch for {queue_path}\n"
               f"  queue nominated under: {want}\n"
               f"  this box has:          {have}")
        if not allow_mismatch:
            raise SystemExit(
                f"REFUSING -- {msg}\n"
                "  Confirming under different engines measures a different program than "
                "the one that was flagged. Pass --allow-engine-mismatch only if you mean "
                "to compare ACROSS versions; the artifact is then not a confirm of this "
                "queue.")
        print(f"[warn] {msg}\n  proceeding under --allow-engine-mismatch", flush=True)

    # Honor the queue's harness budget, not this checkout's constant. Both `run_engine`
    # (subprocess timeout) and `_effective_ms` (the score a killed engine receives) read
    # this module global at call time, so rebinding it is what makes the re-run use the
    # same budget the nomination did. A different budget would silently change every
    # ratio involving a timeout.
    q_budget = queue.get("harness_timeout_s")
    if isinstance(q_budget, (int, float)) and q_budget != run_eval.HARNESS_TIMEOUT_S:
        print(f"[note] harness budget {run_eval.HARNESS_TIMEOUT_S}s -> {q_budget}s "
              f"(from queue)", flush=True)
        run_eval.HARNESS_TIMEOUT_S = q_budget

    slow_ms, engine_ratio = queue["slow_ms"], queue["engine_ratio"]
    window = queue.get("window") or {}
    final_path, partial_path = _out_paths(queue_path, window, shard)

    todo = list(queue["queue"])
    if shard is not None:
        i, n = shard
        # Deterministic stride over the queue's own order (run_eval sorted it by
        # regex/api/n/flags), so shards are disjoint and their union is exact without
        # any coordination between boxes.
        todo = [c for idx, c in enumerate(todo) if idx % n == i]

    records, done_keys = [], set()
    if resume and os.path.exists(partial_path):
        prev = json.load(open(partial_path))
        records = prev.get("verdicts", [])
        done_keys = {_key(r) for r in records}
        print(f"[resume] {len(records)} verdict(s) recovered from {partial_path}",
              flush=True)

    pending = [c for c in todo if _key(c) not in done_keys]
    scratch = os.path.join(scratch_root, f"{window.get('start')}_{window.get('end')}"
                                         f"{'' if shard is None else f'_s{shard[0]}'}")
    os.makedirs(scratch, exist_ok=True)
    box = _box()

    print(f"\n=== confirming {queue_path} ===")
    print(f"    window {window.get('start')}-{window.get('end')}  engines {engines}")
    print(f"    candidates {len(queue['queue'])}"
          + (f"  shard {shard[0]}/{shard[1]} -> {len(todo)}" if shard else "")
          + f"  already done {len(done_keys)}  to run {len(pending)}")
    print(f"    slow_ms {slow_ms}  engine_ratio {engine_ratio}  "
          f"budget {run_eval.HARNESS_TIMEOUT_S}s")
    print(f"    worst case {len(pending) * len(engines) * run_eval.HARNESS_TIMEOUT_S}s "
          f"on this box; heartbeat every {HEARTBEAT_S}s", flush=True)

    start_t = last_print = time.monotonic()
    n_conf = sum(1 for r in records if r["verdict"] == "confirmed")

    def checkpoint(status):
        _atomic_write_json(partial_path, _assemble(
            queue, records, shard, box, time.monotonic() - start_t, status))

    for i, cand in enumerate(pending, 1):
        rec = _verdict(cand, engines, scratch, slow_ms, engine_ratio)
        records.append(rec)
        v = rec["verdict"]
        if v == "confirmed":
            n_conf += 1
            ms, ratio = rec["serial_ms"], rec["ratio"]
            tag = ("ENGINE-SPECIFIC" if rec["engine_specific_measured"] else
                   "ENGINE-SPECIFIC[>=]" if rec["engine_specific_lower_bound"] else
                   "uniformly slow[censored]" if rec["ratio_censored"] else
                   "uniformly slow")
            rs = "inf" if ratio is None else f"{ratio:.1f}x"
            bound = (f" [>= bound; timed out: {','.join(rec['timed_out'])}]"
                     if rec["timed_out"] else "")
            print(f"  [{i}/{len(pending)}] CONFIRMED {tag} {rec['regex_id']} {rec['api']} "
                  f"#{rec['n']} [{rec['flags'] or 'none'}] "
                  f"{rec['slowest_engine']}={ms[rec['slowest_engine']]:.0f}ms "
                  f"{rec['fastest_engine']}={ms[rec['fastest_engine']]:.0f}ms ({rs}){bound}",
                  flush=True)
            last_print = time.monotonic()
        elif v in ("unmeasured", "no_harness"):
            why = ("no harness source in queue" if v == "no_harness"
                   else "no engine reported exec_ms or timed out on re-execution")
            print(f"  ? {v.upper()} {rec['regex_id']} {rec['api']} #{rec['n']} "
                  f"[{rec['flags'] or 'none'}] -- {why} "
                  f"(pool saw ms={rec['pool_ms']} timeout={rec['pool_timeout']})",
                  flush=True)
            last_print = time.monotonic()
        elif time.monotonic() - last_print >= HEARTBEAT_S:
            print(f"  ... {i}/{len(pending)} re-executed, {n_conf} confirmed so far "
                  f"(elapsed {time.monotonic() - start_t:.0f}s)", flush=True)
            last_print = time.monotonic()

        if i % checkpoint_every == 0:
            checkpoint("in_progress")

    report = _assemble(queue, records, shard, box, time.monotonic() - start_t, "complete")
    _atomic_write_json(final_path, report)
    if os.path.exists(partial_path):
        os.remove(partial_path)

    print(f"\n--- {window.get('start')}-{window.get('end')}"
          + (f" shard {shard[0]}/{shard[1]}" if shard else "") + " done in "
          f"{report['confirm_elapsed_s']:.0f}s ---")
    print(f"    confirmed {len(report['confirmed'])} ({_es_summary(report['confirmed'])})  "
          f"load artifacts {report['load_artifacts']}  unmeasured {report['unmeasured']}")
    print(f"    -> {final_path}", flush=True)
    return final_path


def merge(paths_in: list, out_path: str) -> None:
    """Merge shard reports for ONE window into a single redos_<window>.json.

    Refuses to mix windows or engine versions: a merged artifact whose entries were
    measured against different engines would present two incomparable measurements as
    one result set.
    """
    reports = []
    for p in paths_in:
        d = json.load(open(p))
        if d.get("status") != "complete":
            raise SystemExit(f"REFUSING: {p} has status={d.get('status')!r}, not 'complete'")
        reports.append((p, d))
    windows = {json.dumps(d.get("window"), sort_keys=True) for _, d in reports}
    if len(windows) != 1:
        raise SystemExit(f"REFUSING: shards span multiple windows: {windows}")
    versions = {json.dumps(d.get("engine_versions"), sort_keys=True) for _, d in reports}
    if len(versions) != 1:
        raise SystemExit(f"REFUSING: shards measured under different engines: {versions}")

    base = reports[0][1]
    records, seen = [], set()
    for p, d in reports:
        for r in d.get("verdicts", []):
            k = _key(r)
            if k in seen:
                raise SystemExit(f"REFUSING: duplicate candidate {k} across shards "
                                 f"(overlapping --shard assignment?)")
            seen.add(k)
            records.append(r)
    records.sort(key=lambda r: (int(r["regex_id"].split("_")[1]), r["api"], r["n"],
                                r["flags"]))
    merged = _assemble({**base, "_source_path": [d.get("queue_source") for _, d in reports]},
                       records, None, base.get("confirm_box", {}),
                       sum(d.get("confirm_elapsed_s") or 0 for _, d in reports), "complete")
    merged["merged_from"] = [{"path": p, "shard": d.get("shard"),
                              "box": (d.get("confirm_box") or {}).get("hostname"),
                              "verdicts": d.get("verdicts_total")} for p, d in reports]
    merged["confirm_box"] = [d.get("confirm_box") for _, d in reports]
    _atomic_write_json(out_path, merged)

    expected = base.get("candidates")
    print(f"merged {len(reports)} shard(s) -> {out_path}")
    print(f"    verdicts {len(records)}" +
          (f" of {expected} nominated" if expected is not None else "") +
          ("  [INCOMPLETE -- shards missing]" if expected and len(records) != expected else ""))
    print(f"    confirmed {len(merged['confirmed'])} ({_es_summary(merged['confirmed'])})  "
          f"load artifacts {merged['load_artifacts']}  unmeasured {merged['unmeasured']}")


def _parse_shard(s: str | None):
    if s is None:
        return None
    try:
        i, n = s.split("/")
        i, n = int(i), int(n)
    except ValueError:
        raise SystemExit(f"--shard must look like i/N, got {s!r}")
    if not (n >= 1 and 0 <= i < n):
        raise SystemExit(f"--shard i/N needs N>=1 and 0<=i<N, got {s!r}")
    return (i, n)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queue", action="append", default=[],
                    help="a deferred redos_queue_<window>.json; repeatable, processed "
                         "in order, each producing its own report")
    ap.add_argument("--merge", nargs="+", metavar="REPORT",
                    help="merge completed shard reports for ONE window into --out")
    ap.add_argument("--out", help="output path for --merge")
    ap.add_argument("--shard", default=None,
                    help="i/N -- confirm only candidates where index %% N == i. Shard "
                         "across BOXES, never across cores: parallelism on one box "
                         "reintroduces the contention that made nominations untrustworthy.")
    ap.add_argument("--resume", action="store_true",
                    help="continue from redos_<window>.partial.json if present")
    ap.add_argument("--checkpoint-every", type=int, default=10,
                    help="rewrite the partial artifact every N candidates (default 10)")
    ap.add_argument("--allow-engine-mismatch", action="store_true",
                    help="proceed when this box's engines differ from the queue's. The "
                         "result is a cross-version comparison, NOT a confirm.")
    ap.add_argument("--scratch", default=None,
                    help="where to materialize inlined harnesses (default: alongside "
                         "the queue, in .confirm_scratch/)")
    args = ap.parse_args()

    if args.merge:
        if not args.out:
            raise SystemExit("--merge requires --out")
        merge(sorted(f for pat in args.merge for f in (glob.glob(pat) or [pat])), args.out)
        return
    if not args.queue:
        raise SystemExit("nothing to do: pass --queue <redos_queue_*.json> (or --merge)")

    shard = _parse_shard(args.shard)
    scratch_root = args.scratch or os.path.join(
        os.path.dirname(os.path.abspath(args.queue[0])), ".confirm_scratch")
    t0 = time.monotonic()
    outs = [confirm_queue(q, shard, args.resume, args.checkpoint_every,
                          args.allow_engine_mismatch, scratch_root)
            for q in args.queue]
    print(f"\n=== all {len(outs)} queue(s) confirmed in {time.monotonic() - t0:.0f}s ===")
    for o in outs:
        print(f"    {o}")


if __name__ == "__main__":
    main()
