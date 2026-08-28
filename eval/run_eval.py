"""eval/ -- differential runner over a deterministic corpus slice.

Runs every synthesized ``(regex_id, api, n)`` harness on node / bun / deno,
captures stdout / stderr / exit code SEPARATELY per engine, extracts each engine's
single canonical JSON line, and diffs the ``value`` across engines. Reports a
headline discrepancy count and writes full per-(regex, api) diff artifacts to
``results/<regex_id>/<api>.diff.json``.

Output-capture fidelity is the whole point (settled doc):
- The canonical result is the ONE stdout line that parses as our JSON envelope.
- An engine-thrown regex error is emitted by the harness as ``ok:false, error`` --
  a COMPARABLE outcome, diffed like any value.
- A process failure (nonzero exit, or no canonical line) is a RUN DEFECT: recorded
  and surfaced, but not compared as a value (it is not a regex-semantics signal).
- Blowing the wall-clock budget is a TIMEOUT, tracked on its own axis and disjoint
  from defect. An engine still backtracking when it is killed is the ReDoS tracker's
  sharpest result, not a malfunction; folding it into `defect_cases` would file it
  as run infrastructure noise. See ``run_engine`` and ``_outcome``.

Parallel (uniform): ``--workers N`` runs the ``(regex, api)`` units concurrently on
a thread pool (engine subprocesses are I/O/startup-bound, so threads scale well).
Worker count is NOT part of provenance -- it changes wall-clock, never results:
totals are commutative sums and the discrepancy list is sorted deterministically, so
a run at ``--workers 12`` yields the same headline as ``--workers 1``.

Monitoring + resumability (uniform, no per-instance logic):
- A flushed heartbeat (``[done/N units] cases=.. discrep=.. defects=.. timeouts=..
  elapsed eta``)
  prints every 50 completed units, and each discrepancy/defect is announced LIVE so a
  long run shows signal as it happens, not only at the end.
- ``eval_headline_<start>_<end>.json`` is rewritten after EVERY regex (atomically), so
  a killed run always leaves a current, complete-JSON headline for monitoring. It is
  named for the window it covers, and ``complete`` is scoped to that window: a second
  chunk writes its own headline instead of overwriting the first's.
- Every artifact (diff.json, headline) is written tmp+rename, so a crash mid-write
  can never leave a half file that would poison ``--resume`` or monitoring.
- ``--resume`` reuses an existing ``<rid>/<api>.diff.json`` ONLY if it was computed
  under the same resolved config + git commit AND the same engine versions;
  anything else is recomputed. Stale results are never silently mixed in.

Usage:  python eval/run_eval.py [--skip-generate] [--resume] [--limit N] [--config P]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from pipeline.config import (  # noqa: E402
    Config, load_config, seed_everything, provenance, clear_chunk_context,
)
from pipeline.run import generate_all  # noqa: E402
import paths  # noqa: E402
# Shared with confirm_redos.py and the offline backfill so all three classify a
# confirmed row identically; see the module docstring for why it is not inlined here.
from redos_ratio import ratio_fields as _ratio_fields  # noqa: E402

# Per-engine argv prefix (validated invocation).
ENGINE_CMD = {
    "node": ["node"],
    "bun": ["bun"],
    "deno": ["deno", "run", "--quiet"],
}
# Per-engine environment overlay, empty for the three real engines. It exists so an
# engine can be defined by an ENV VAR rather than an argv flag: JavaScriptCore's tier
# control is `BUN_JSC_useRegExpJIT=0`, with no command-line equivalent, and the
# A JIT-vs-interpreter differential registers
# such variants as ordinary pseudo-engines so every existing code path applies unchanged.
ENGINE_ENV: dict[str, dict[str, str]] = {}
# Per-harness wall-clock budget. A harness is a tiny synchronous script, so blowing
# this is never routine -- but it is not automatically a defect either: an engine
# backtracking on a pathological pattern is the RESULT this tracker looks for. See
# run_engine, which classifies the two apart.
HARNESS_TIMEOUT_S = 20
# Longest silence the serial confirm phase may go without printing. Each candidate can
# legitimately cost len(engines) * HARNESS_TIMEOUT_S, and the phase only speaks up on a
# CONFIRMED/UNMEASURED verdict, so a run of load artifacts or timeouts would otherwise
# look exactly like a hang.
_CONFIRM_HEARTBEAT_S = 30


def engine_versions(engines: tuple[str, ...]) -> dict:
    versions = {}
    for e in engines:
        try:
            out = subprocess.run([e, "--version"], capture_output=True, text=True, timeout=15)
            versions[e] = out.stdout.strip().splitlines()[0] if out.stdout.strip() else "unknown"
        except (FileNotFoundError, subprocess.TimeoutExpired) as ex:
            versions[e] = f"unavailable-{type(ex).__name__}"
    return versions


def _extract_canonical(stdout: str) -> dict | None:
    """The single JSON envelope line ({api, regex_id, ok, ...}). None if absent.

    Split ONLY on "\n" (the delimiter the harness emits), NOT str.splitlines():
    a matched string can legitimately contain U+0085/U+2028/U+2029, which
    JSON.stringify leaves unescaped (they are >= 0x20) but splitlines() treats as
    line boundaries -- that would shred the one-line envelope and fake a defect.
    A real newline inside a value IS JSON-escaped, so it never splits the line.
    """
    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "ok" in obj and "api" in obj and "regex_id" in obj:
            return obj
    return None


def _comparable(canonical: dict) -> str:
    """Canonical, engine-independent serialization of the comparable outcome.

    Compares only the semantic result (ok + value/error), not api/regex_id which
    are constant. Sorted keys so object key-order can never fake a discrepancy.
    """
    core = {"ok": canonical.get("ok")}
    if canonical.get("ok"):
        core["value"] = canonical.get("value")
    else:
        core["error"] = canonical.get("error")
    return json.dumps(core, sort_keys=True, ensure_ascii=True)


def run_engine(engine: str, harness_path: str) -> dict:
    """Run one harness on one engine; capture stdout/stderr/exit separately."""
    cmd = ENGINE_CMD[engine] + [harness_path]
    overlay = ENGINE_ENV.get(engine)
    env = {**os.environ, **overlay} if overlay else None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=HARNESS_TIMEOUT_S,
                              env=env)
        exit_code, stdout, stderr, timed_out = proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as e:
        exit_code, stdout, stderr, timed_out = None, (e.stdout or ""), (e.stderr or ""), True
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")

    canonical = _extract_canonical(stdout)
    # Two failure classes, deliberately MUTUALLY EXCLUSIVE:
    #   timed_out -- the engine blew the wall-clock budget. On a backtracking regex that
    #     is the RESULT we are probing for, not a malfunction, so it is counted on its
    #     own axis and reported through the ReDoS artifact (see _timed_out_engines).
    #   defect -- the harness genuinely malfunctioned: nonzero exit, or no canonical line.
    # A timeout trips BOTH of defect's disjuncts unaided (exit_code is None, and the
    # envelope prints only after the api call returns, so canonical is None too). That is
    # why timed_out has to SUPPRESS defect: merely dropping `timed_out or` from this
    # expression would change nothing at all.
    defect = not timed_out and (exit_code not in (0,) or canonical is None)
    return {
        "engine": engine, "exit": exit_code, "timed_out": timed_out,
        "stdout": stdout, "stderr": stderr,
        "canonical": canonical,
        "comparable": _comparable(canonical) if canonical is not None else None,
        "defect": defect,
    }


def _outcome(runs: dict) -> tuple[bool, bool]:
    """``(any_defect, any_timeout)`` for one case's runs.

    Derived from the per-run fields rather than read back from a stored ``any_defect``,
    because a diff.json written before timeouts were split out of ``defect`` recorded
    ``defect: true`` on a timed-out engine. Masking with ``timed_out`` -- which every
    artifact has always carried -- makes an old record tally IDENTICALLY to a fresh one,
    which is the resume uniformity :func:`_tally` promises.
    """
    any_timeout = any(r["timed_out"] for r in runs.values())
    any_defect = any(r["defect"] and not r["timed_out"] for r in runs.values())
    return any_defect, any_timeout


def _diff_one(regex_id: str, api: str, n: int, flags: str, engines: tuple[str, ...]) -> dict:
    """Run one (regex, api, string, flag-set) case across all engines and classify."""
    hpath = paths.api_harness_path(regex_id, api, n, flags)
    runs = {e: run_engine(e, hpath) for e in engines}

    # Value discrepancy: distinct comparable outcomes among engines that produced one.
    comparables = {e: r["comparable"] for e, r in runs.items() if r["comparable"] is not None}
    distinct = set(comparables.values())
    value_discrepancy = len(distinct) > 1
    any_defect, any_timeout = _outcome(runs)

    return {
        "n": n,
        "flags": flags,
        "value_discrepancy": value_discrepancy,
        "any_defect": any_defect,
        "any_timeout": any_timeout,
        "distinct_values": sorted(distinct),
        "runs": runs,
    }


def _strings_meta(regex_id: str, api: str) -> dict:
    """The strings.jsonl meta line (count + flag_variants), or an empty stub."""
    spath = paths.api_strings_path(regex_id, api)
    if not os.path.exists(spath):
        return {"count": 0, "flag_variants": []}
    with open(spath) as f:
        return json.loads(f.readline())


def _atomic_write_json(path: str, obj: dict) -> None:
    """Write JSON via tmp+rename so a crash mid-write never leaves a half file. A
    partial diff/headline would poison ``--resume`` and monitoring; the atomic
    swap makes any present file guaranteed-complete (same pattern the overnight
    generation runner uses)."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


def _canon(obj) -> str:
    """Canonical JSON string for equality that is stable across a JSON round-trip.
    A stored artifact has been through ``json.dump``/``load`` (so tuples became
    lists, key order is whatever), while the live ``provenance``/versions are
    in-memory (tuples). Comparing canonical dumps -- sorted keys -- makes those
    representations compare equal iff they are semantically identical."""
    return json.dumps(obj, sort_keys=True)


def _load_valid_diff(rid: str, api: str, cur_prov: str, cur_versions: str) -> dict | None:
    """An existing ``<rid>/<api>.diff.json`` that is safe to REUSE under ``--resume``.

    Reuse requires the artifact to be present, parseable, and computed under the
    SAME resolved config + git commit (``provenance``) AND the SAME engine versions
    (compared as canonical JSON via :func:`_canon`, so a tuple/list round-trip
    difference is not mistaken for a change). Anything else returns ``None`` ->
    recompute, so a code/config/engine change never silently mixes stale results
    into a fresh headline. Because diffs are written atomically, a present file is
    always complete JSON: an unparseable one is real corruption and raises (fail
    loud), not a cache miss."""
    dpath = paths.api_diff_path(rid, api)
    if not os.path.exists(dpath):
        return None
    with open(dpath) as f:
        art = json.load(f)  # atomic writes => a present file is complete JSON
    if _canon(art.get("provenance")) == cur_prov and _canon(art.get("engine_versions")) == cur_versions:
        return art
    return None


def _engine_ms(case: dict) -> dict:
    """``{engine -> exec_ms}`` for the engines in `case` that reported a timing.

    Absent for a defect (no canonical line) and for a thrown regex error (the error
    envelope carries no ``exec_ms``), so a missing entry means "not measured", never
    "fast". Guards on the type because ``exec_ms`` is absent from every diff.json
    written before the tracker existed -- an old artifact reused via ``--resume``
    simply contributes no candidates rather than crashing the run.
    """
    out = {}
    for engine, r in case["runs"].items():
        canonical = r.get("canonical")
        if canonical is None:
            continue
        ms = canonical.get("exec_ms")
        if isinstance(ms, (int, float)) and not isinstance(ms, bool):
            out[engine] = float(ms)
    return out


def _timed_out_engines(case: dict) -> list:
    """Engines that blew the harness wall-clock, sorted.

    These are the ReDoS cases that MATTER, and they are exactly the ones ``exec_ms``
    cannot see: the harness prints its envelope only after the api call returns, so an
    engine still backtracking when the budget expires is SIGKILLed having printed
    nothing. Its timing is not slow -- it is ABSENT.

    Measured live on /(a+)+$/ vs a 32-char non-matching input ("a"*31 + "!"): node and
    deno (both V8) run for MINUTES and are killed at HARNESS_TIMEOUT_S; bun 686ms
    (JavaScriptCore, does not blow up). The V8 side is an exponential blowup, so its
    wall-clock is machine-dependent and worth no precise figure -- one unloaded host
    gave node 186s / deno 149s, i.e. ~9x and ~7x the budget. bun's 686ms reproduces
    exactly, and it is the whole problem: reading ``exec_ms`` alone sees ONLY that
    number, under the 1000ms threshold, and concludes the case is fine -- discarding
    the sharpest engine-specific result in the corpus. A timeout is the strongest
    ReDoS evidence available, not its absence, so it nominates a candidate outright.
    """
    return sorted(e for e, r in case["runs"].items() if r.get("timed_out"))


def _effective_ms(case: dict) -> tuple[dict, list]:
    """``({engine -> ms}, [timed_out engines])`` for ranking slowest vs fastest.

    A timed-out engine is scored at the harness budget, which is a LOWER BOUND on its
    real cost (node's true 186s reads as 20000ms), never a measurement. That keeps the
    comparison sound in the only direction that matters: it UNDERSTATES the gap, so a
    case flagged engine-specific is at least that lopsided, never less.
    """
    timed_out = _timed_out_engines(case)
    effective = _engine_ms(case)
    for engine in timed_out:
        effective[engine] = float(HARNESS_TIMEOUT_S * 1000)
    return effective, timed_out


def _tally(per_case: list, rid: str, api: str, totals: dict,
           discrepancy_index: list, announce: bool,
           candidates: list, slow_ms: int) -> None:
    """Fold one (rid, api)'s per-case results into the running totals + discrepancy
    index. IDENTICAL accounting whether the results were just computed or reused
    from disk (uniform -- a resumed run and a from-scratch run give the same
    headline; see :func:`_outcome`, which is what keeps that true across the
    defect/timeout split). When ``announce``, surface each discrepancy/defect LIVE so
    a long run shows signal as it happens, not only at the end.

    A case whose engine timed out is counted as a TIMEOUT, never a defect: the engine
    did exactly what this tracker probes for. It is reported through the ReDoS artifact,
    and the two counters are disjoint, so ``defect_cases`` means only "the harness
    malfunctioned" and can be read at face value in the headline.

    Also collects ReDoS CANDIDATES: any case that either exceeded ``slow_ms`` on some
    engine OR timed out on some engine (see :func:`_timed_out_engines` -- a timeout is
    a candidate precisely BECAUSE it reports no ``exec_ms``). These observations were
    taken under pool load, so they are only nominations for the serial confirm phase
    (:func:`_confirm_redos`) -- nothing here is reported as a finding.
    """
    for c in per_case:
        totals["cases"] += 1
        if c["value_discrepancy"]:
            totals["value_discrepancies"] += 1
            discrepancy_index.append({"regex_id": rid, "api": api,
                                      "n": c["n"], "flags": c["flags"]})
            if announce:
                tag = c["flags"] or "none"
                print(f"  ! DISCREPANCY {rid} {api} #{c['n']} [{tag}] "
                      f"-> results/{rid}/{api}.diff.json", flush=True)
        any_defect, any_timeout = _outcome(c["runs"])
        if any_defect:
            totals["defect_cases"] += 1
            if announce:
                tag = c["flags"] or "none"
                exits = " ".join(f"{e}:{r['exit']}{'/TO' if r['timed_out'] else ''}"
                                 for e, r in c["runs"].items())
                print(f"  ! DEFECT {rid} {api} #{c['n']} [{tag}] ({exits}) "
                      f"-> results/{rid}/{api}.diff.json", flush=True)
        if any_timeout:
            totals["timeout_cases"] += 1
            if announce:
                tag = c["flags"] or "none"
                tos = ",".join(_timed_out_engines(c))
                print(f"  ~ TIMEOUT {rid} {api} #{c['n']} [{tag}] ({tos} over "
                      f"{HARNESS_TIMEOUT_S}s) -> ReDoS candidate, confirmed serially "
                      f"below", flush=True)
        slow = {e: ms for e, ms in _engine_ms(c).items() if ms > slow_ms}
        timed_out = _timed_out_engines(c)
        if slow or timed_out:
            candidates.append({"regex_id": rid, "api": api, "n": c["n"],
                               "flags": c["flags"], "observed_ms": slow,
                               "observed_timeout": timed_out})


def _build_redos_queue(candidates: list, patterns: dict, config: Config,
                       versions: dict, prov: dict, window: tuple[int, int]) -> dict:
    """Package nominated candidates as a SELF-CONTAINED work order for a later box.

    The serial confirm phase is ~43s per candidate on one core while the rest of the
    machine idles, and it dominated the last two windows: 6h57m of a 17h18m run (40%),
    5h19m of the one before. Deferring it takes that off the critical path so a run
    covers more corpus rows per unit wall-clock; :func:`_confirm_redos` then runs
    elsewhere, against this queue, on a quiet box.

    Each candidate carries its harness SOURCE inline rather than a path. `_diff_one`
    re-executes ``results/<rid>/<api>__<n>__<flags>.js`` off disk, so a queue of bare
    pointers is only meaningful on the machine that generated it -- shipping it
    anywhere would mean rsyncing the whole results tree. Inlined, the queue is one
    portable file (~3KB per candidate; the 561-candidate window would be ~2MB), and
    the harness text doubles as the exact provenance of what ran: it IS the executed
    artifact, not a reference to something that may have changed since.

    ``engine_versions`` is recorded so the consumer can REFUSE a queue nominated under
    different engines. Nominating under bun 1.3.14 and confirming under 1.3.15 would
    silently measure a different program than the one that was flagged.
    """
    out = []
    for cand in candidates:
        rid, api, n, flags = cand["regex_id"], cand["api"], cand["n"], cand["flags"]
        hpath = paths.api_harness_path(rid, api, n, flags)
        try:
            with open(hpath) as fh:
                source = fh.read()
        except OSError:
            # Keep the candidate: a missing harness is worth surfacing downstream, and
            # dropping it here would quietly shrink the queue below the nominated count.
            source = None
        out.append({**cand, "pattern": patterns.get(rid),
                    "harness_path": hpath, "harness_source": source})
    missing = sum(1 for c in out if c["harness_source"] is None)
    return {
        "window": {"start": window[0], "end": window[1]},
        "engine_versions": versions, "provenance": prov,
        "slow_ms": config.redos_slow_ms, "engine_ratio": config.redos_engine_ratio,
        "harness_timeout_s": HARNESS_TIMEOUT_S,
        "engines": list(config.engines),
        "status": "deferred",
        "caveat": ("NOMINATIONS ONLY -- every observed_ms here was taken under pool "
                   "load and is inflated. Nothing in this file is a finding until a "
                   "serial, unloaded re-run confirms it. Confirm with the same engine "
                   "versions recorded above; ratios survive a change of box, absolute "
                   "milliseconds do not."),
        "candidates": len(out),
        "harnesses_missing": missing,
        "queue": out,
    }


def _confirm_redos(candidates: list, patterns: dict, config: Config) -> dict:
    """Re-execute every ReDoS candidate SERIALLY, and keep only the ones still slow.

    Candidate timings come from the parallel pool, where workers saturate the cores and
    inflate every reading -- this runner's own ``--workers`` guidance is that load can
    turn a slow-but-valid ReDoS case into a timeout defect. So a pool reading NOMINATES;
    only an unloaded re-run MEASURES. This phase runs after the pool has fully drained,
    one case at a time, which is the entire point: nothing else is competing for CPU.

    A confirmed case is flagged ``engine_specific`` when the slowest engine is still over
    budget AND slowest/fastest >= ``redos_engine_ratio``. One engine backtracking where
    its peers do not is a differential result about the ENGINE -- the thing this project
    reports. A case uniformly slow on every engine is a property of the regex itself; it
    is kept in the artifact but not flagged, because there is no differential in it.

    A timed-out engine is scored at the harness budget rather than skipped (see
    :func:`_effective_ms`): the extreme cases print no ``exec_ms`` at all, and dropping
    them for lack of a reading would discard the strongest findings. Where that happens
    the recorded ms/ratio are lower bounds, marked ``is_lower_bound``, and the ratio is
    ``ratio_censored`` -- see :func:`_ratio_fields`, which owns the classification for
    this path and the deferred one alike. Read
    ``engine_specific_measured``/``engine_specific_lower_bound``, not the
    ``engine_specific`` union, when counting: the union mixes measured gaps with rows
    whose slow side merely ran out the clock.

    This does NOT prove ReDoS. Catastrophic backtracking means runtime growing
    superlinearly in INPUT LENGTH, and nothing here varies length. The strings are not
    short (p50 21 chars, p90 60, max 285 over the 6000-9999 window) -- they are
    UNRELATED, and a growth curve cannot be fitted across strings that share no shape,
    because each carries its own constant factor. The gap is a length FAMILY (one shape
    at growing n), not longer strings. A confirmed case is engine-specific slowness
    until one exists.
    """
    result = {"candidates": len(candidates), "confirmed": [],
              "load_artifacts": 0, "unmeasured": 0}
    start_t = last_print = time.monotonic()

    def _spoke() -> None:
        """Mark that this candidate produced a verdict line -- the heartbeat exists to
        break silence, so any real output postpones it."""
        nonlocal last_print
        last_print = time.monotonic()

    for i, cand in enumerate(candidates, 1):
        rid, api, n, flags = cand["regex_id"], cand["api"], cand["n"], cand["flags"]
        case = _diff_one(rid, api, n, flags, config.engines)
        ms, timed_out = _effective_ms(case)
        if time.monotonic() - last_print >= _CONFIRM_HEARTBEAT_S:
            print(f"  ... {i}/{len(candidates)} candidates re-executed, "
                  f"{len(result['confirmed'])} confirmed so far "
                  f"(elapsed {time.monotonic() - start_t:.0f}s)", flush=True)
            _spoke()
        if not ms:
            # The pool flagged it; the serial re-run reports nothing at all (every
            # engine threw, or crashed without timing out). Surface it -- silently
            # dropping would hide exactly the cases worth a human's attention.
            result["unmeasured"] += 1
            print(f"  ? UNMEASURED {rid} {api} #{n} [{flags or 'none'}] -- no engine "
                  f"reported exec_ms or timed out on re-execution "
                  f"(pool saw ms={cand['observed_ms']} timeout={cand['observed_timeout']})",
                  flush=True)
            _spoke()
            continue
        rf = _ratio_fields(ms, timed_out, config.redos_engine_ratio)
        slowest, fastest = rf["slowest_engine"], rf["fastest_engine"]
        if ms[slowest] <= config.redos_slow_ms:
            # Fast once unloaded: the pool reading was contention, not the regex. A
            # timed-out engine scores at the budget, so it can never land here.
            result["load_artifacts"] += 1
            continue
        result["confirmed"].append({
            "regex_id": rid, "api": api, "n": n, "flags": flags,
            "pattern": patterns.get(rid),
            "pool_ms": cand["observed_ms"], "pool_timeout": cand["observed_timeout"],
            "serial_ms": ms, "timed_out": timed_out,
            # ms/ratio are LOWER BOUNDS when timed_out is non-empty: a killed engine is
            # scored at the harness budget, and its real cost is unbounded above it.
            "is_lower_bound": bool(timed_out),
            **rf,
        })
        ratio = rf["ratio"]
        tag = ("ENGINE-SPECIFIC" if rf["engine_specific_measured"] else
               "ENGINE-SPECIFIC[>=]" if rf["engine_specific_lower_bound"] else
               "uniformly slow[censored]" if rf["ratio_censored"] else "uniformly slow")
        rs = "inf" if ratio is None else f"{ratio:.1f}x"
        bound = f" [>= bound; timed out: {','.join(timed_out)}]" if timed_out else ""
        print(f"  [{i}/{len(candidates)}] CONFIRMED {tag} {rid} {api} #{n} "
              f"[{flags or 'none'}] {slowest}={ms[slowest]:.0f}ms "
              f"{fastest}={ms[fastest]:.0f}ms ({rs}){bound}", flush=True)
        _spoke()
    return result


def _compute_api(o: dict, api_summary: dict, config: Config, versions: dict,
                 prov: dict) -> list:
    """Run every case of ONE (regex, api) across all engines and write its diff.json.

    Runs in a worker thread: it only spawns engine subprocesses and writes its OWN
    ``<rid>/<api>.diff.json`` (atomic, distinct path -- no shared state), then returns
    the per-case results for the main thread to tally. ``prov`` is passed in so a
    worker never shells out to git. ``per_case`` is built in (n, flags) order, so the
    artifact's contents are identical regardless of how workers were scheduled."""
    rid, api = o["regex_id"], api_summary["api"]
    meta = _strings_meta(rid, api)
    num = int(meta.get("count", 0))
    variants = meta.get("flag_variants") or [api_summary.get("flags", "")]
    per_case = [_diff_one(rid, api, n, flags, config.engines)
                for n in range(num) for flags in variants]
    diff_artifact = {
        "regex_id": rid, "api": api, "pattern": o["pattern"],
        "engine_versions": versions, "provenance": prov,
        "num_strings": num, "flag_variants": variants, "results": per_case,
    }
    _atomic_write_json(paths.api_diff_path(rid, api), diff_artifact)
    return per_case


def _build_headline(versions: dict, units_done: int, units_total: int, n_regexes: int,
                    totals: dict, discrepancy_index: list, cache: dict, prov: dict,
                    window: tuple[int, int], redos: dict | None = None) -> dict:
    """The headline dict. Progress is tracked in (regex, api) UNITS (the parallel work
    item); ``complete`` flips true only when every unit is done. Written incrementally
    so a killed run is honestly labeled ``complete: false``.

    ``window`` is the corpus range this headline describes. ``complete`` is scoped to
    THAT window, not to whatever else lives in results/: it means "every unit of this
    record ran", so record the window alongside it rather than let a reader assume the
    number covers the whole directory.

    ``redos`` is a COUNTS-ONLY summary pointing at the full redos_<window>.json; it is
    None for the incremental writes during the pool, because the confirm phase has not
    run yet at that point. ``None`` there means "not computed yet", which is why it is
    omitted from the dict entirely rather than written as a zeroed summary that a
    monitoring reader would take for "no slow cases found".
    """
    headline = {
        "engine_versions": versions,
        "window": {"start": window[0], "end": window[1]},
        "regexes_evaluated": n_regexes,
        "units_done": units_done,
        "units_total": units_total,
        "complete": units_done >= units_total,
        "totals": totals,
        "cache": cache,
        "discrepancies": discrepancy_index,
        "provenance": prov,
    }
    if redos is not None:
        headline["redos"] = {
            "candidates": redos["candidates"],
            "confirmed": len(redos["confirmed"]),
            # Union, kept for continuity with windows confirmed before the split. It
            # mixes measured gaps with censored lower bounds -- read the two components.
            "engine_specific": sum(1 for c in redos["confirmed"] if c["engine_specific"]),
            "engine_specific_measured": sum(
                1 for c in redos["confirmed"] if c.get("engine_specific_measured")),
            "engine_specific_lower_bound": sum(
                1 for c in redos["confirmed"] if c.get("engine_specific_lower_bound")),
            # Slow side censored at the budget and the ratio fell UNDER the gate: not a
            # differential, but not evidence against one either. Unresolved at this budget.
            "unresolved_censored": sum(
                1 for c in redos["confirmed"]
                if c.get("ratio_censored") and not c["engine_specific"]),
            "load_artifacts": redos["load_artifacts"],
            "unmeasured": redos["unmeasured"],
        }
        # A deferred window has candidates but zero confirmed, which reads exactly like
        # "nominated, all were load artifacts" unless the distinction is recorded. Flag
        # it so no consumer can total `confirmed` across windows that never confirmed.
        if redos.get("deferred"):
            headline["redos"]["deferred"] = True
            headline["redos"]["queue_path"] = redos.get("queue_path")
    return headline


def _load_run_record(path: str) -> dict:
    """Load a run record, failing loudly and actionably when the window is absent.

    Records are per-window (run_record_<start>_<end>.json), so asking for a window
    that was never generated is a real mistake -- naming the records that DO exist
    beats a bare FileNotFoundError, and beats silently falling back to another
    window's record.
    """
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        available = paths.find_run_records()
        listing = "\n".join(f"  {os.path.basename(p)}" for p in available) or "  (none)"
        raise SystemExit(
            f"no run record for this window: {path}\n"
            f"available records in {paths.RESULTS_DIR}:\n{listing}\n"
            f"Pass --start/--limit matching a record above, or point at one with "
            f"--record PATH."
        )


def _record_window(run_record: dict) -> tuple[int, int]:
    """The window [lo, hi) the record's outcomes actually cover.

    Taken from the outcomes rather than the record's start/limit so the headline is
    named for the rows it truly describes, even for a merged/rebuilt record whose
    window is not a single first-N slice.
    """
    indices = [o["index"] for o in run_record["outcomes"] if "index" in o]
    if not indices:
        raise SystemExit("run record has no outcomes with an index -- cannot scope it")
    return min(indices), max(indices) + 1


def run_eval(config: Config, generate: bool = True, limit: int | None = None,
             resume: bool = False, workers: int = 1, start: int = 0,
             record_path: str | None = None, redos_defer: bool = False) -> dict:
    # Line-buffer stdout so the heartbeat is visible live under nohup/pipe redirect
    # (block buffering otherwise hides all progress until the process exits).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if workers < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")
    seed_everything(config)
    slice_n = limit if limit is not None else config.eval_slice

    if generate:
        print(f"=== generating artifacts for corpus rows [{start}, {start + slice_n}) ===")
        run_record = generate_all(config, limit=slice_n, start=start)
    else:
        # Records are per-window; resolve this run's window unless one is named.
        rpath = record_path or paths.run_record_path(start, start + slice_n)
        run_record = _load_run_record(rpath)
        print(f"=== run record: {rpath} ===")

    ok_regexes = [o for o in run_record["outcomes"] if o["status"] == "ok"]
    versions = engine_versions(config.engines)
    n_total = len(ok_regexes)

    totals = {"cases": 0, "value_discrepancies": 0, "defect_cases": 0,
              "timeout_cases": 0}
    discrepancy_index = []  # (regex_id, api, n, flags) pointers; sorted at the end
    redos_candidates = []   # cases >redos_slow_ms under pool load; confirmed serially below
    patterns = {o["regex_id"]: o["pattern"] for o in ok_regexes}
    cache = {"reused": 0, "computed": 0}  # how many (rid,api) diffs were reused vs run
    # Scoped to the record's real window, so evaluating a second chunk cannot
    # overwrite an earlier chunk's headline (see paths.eval_headline_path).
    win_lo, win_hi = _record_window(run_record)
    headline_path = paths.eval_headline_path(win_lo, win_hi)
    # Provenance + engine versions computed ONCE (provenance() shells out to git;
    # per-artifact would be thousands of subprocesses, and workers must not call git).
    #
    # Chunk context is a generation fact, so the eval must not claim one. Clearing it
    # is load-bearing for `--resume`: `generate_all` declares the window it generated,
    # so without this an in-process generate+eval run would stamp chunk_start/count
    # into every diff.json while a later `--skip-generate --resume` computes provenance
    # with them null. `_load_valid_diff` compares provenance whole, so every unit would
    # miss the cache and silently recompute the window -- hours of engine execution
    # presenting itself as a successful resume.
    clear_chunk_context()
    prov = provenance(config)
    cur_prov, cur_versions = _canon(prov), _canon(versions)

    # Pass 1 (deterministic, main thread): split each (regex, api) unit into REUSE vs
    # COMPUTE. Reused diffs are tallied now; compute work is queued for the pool.
    todo = []          # (o, api_summary) units that still need engine execution
    n_items = 0        # total (regex, api) units in scope
    for o in ok_regexes:
        rid = o["regex_id"]
        for api_summary in o["apis"]:
            n_items += 1
            reused = _load_valid_diff(rid, api_summary["api"], cur_prov, cur_versions) \
                if resume else None
            if reused is not None:
                cache["reused"] += 1
                _tally(reused["results"], rid, api_summary["api"],
                       totals, discrepancy_index, announce=False,
                       candidates=redos_candidates, slow_ms=config.redos_slow_ms)
            else:
                todo.append((o, api_summary))

    print(f"\n=== running harnesses on {list(config.engines)} ===")
    print(f"engine versions: {versions}")
    print(f"units: {n_items} (regex,api)  reused: {cache['reused']}  "
          f"to-compute: {len(todo)}  workers: {workers}", flush=True)

    # Pass 2 (parallel): compute the remaining units concurrently. Only subprocess
    # execution + each unit's own diff.json write happen in worker threads; EVERY
    # shared-state update (totals, discrepancy_index) happens here in the main thread
    # as futures complete, so there are no data races. The result is worker-count
    # INDEPENDENT: totals are commutative sums, and discrepancy_index is sorted
    # deterministically at the end -- a parallel run and a sequential run produce the
    # SAME headline numbers. (Caveat: the per-harness wall-clock timeout is the one
    # thing sensitive to load -- heavy oversubscription could turn a slow-but-valid
    # ReDoS case into a TIMEOUT. Defaulting workers to the core count keeps that from
    # happening, and a timeout only ever affects `timeout_cases`, never a value
    # discrepancy -- a stalled engine yields no output to disagree with. It cannot move
    # `defect_cases` either: the two are disjoint by construction in run_engine.)
    HEARTBEAT_EVERY = 50
    done = cache["reused"]
    start_t = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_compute_api, o, api_summary, config, versions, prov):
                (o["regex_id"], api_summary["api"]) for (o, api_summary) in todo}
        for fut in as_completed(futs):
            # pop, NOT [] -- this is the memory fix. `as_completed` drops its own
            # references as it yields (its internal ref_collect sets), so `futs` is the
            # SOLE retainer of every completed Future, and a Future holds its `per_case`
            # payload for as long as it lives. Indexing left all 37,248 of them alive for
            # the whole run: ~2.8 MB/unit, linear growth, 11.7 GiB at 3500 units and
            # 80 GiB (the container cap) at 28,750 -- which is exactly how the
            # 15050-20035 window got OOM-killed at 77%. Popping bounds live payloads to
            # the pool's in-flight set. `futs` is not read after this loop.
            rid, api = futs.pop(fut)
            per_case = fut.result()  # re-raises any worker exception (fail loud)
            cache["computed"] += 1
            _tally(per_case, rid, api, totals, discrepancy_index, announce=True,
                   candidates=redos_candidates, slow_ms=config.redos_slow_ms)
            done += 1
            if done % HEARTBEAT_EVERY == 0 or done == n_items:
                elapsed = time.monotonic() - start_t
                rate = cache["computed"] / elapsed if elapsed > 0 else 0.0
                eta = f"{(len(todo) - cache['computed']) / rate:.0f}s" if rate > 0 else "?"
                print(f"[{done}/{n_items} units] cases={totals['cases']} "
                      f"discrep={totals['value_discrepancies']} defects={totals['defect_cases']} "
                      f"timeouts={totals['timeout_cases']} "
                      f"(computed={cache['computed']}/{len(todo)}) "
                      f"elapsed={elapsed:.0f}s eta~{eta}", flush=True)
                _atomic_write_json(headline_path, _build_headline(
                    versions, done, n_items, n_total, totals, discrepancy_index, cache,
                    prov, (win_lo, win_hi)))

    # Deterministic final ordering (completion order is nondeterministic under
    # parallelism; sort so the headline's discrepancy list is reproducible).
    discrepancy_index.sort(key=lambda d: (int(d["regex_id"].split("_")[1]),
                                          d["api"], d["n"], d["flags"]))

    # Phase 3 (serial, AFTER the pool is fully drained -- the `with` block above has
    # exited, so every worker thread is joined and the machine is quiet). Re-execute
    # the slow candidates unloaded; see _confirm_redos for why a pool reading cannot
    # be trusted on its own.
    redos_candidates.sort(key=lambda d: (int(d["regex_id"].split("_")[1]),
                                         d["api"], d["n"], d["flags"]))
    redos = {"candidates": 0, "confirmed": [], "load_artifacts": 0, "unmeasured": 0}
    redos_path = queue_path = None
    if redos_defer:
        # Deferred: nominate here, measure elsewhere. Written even when the queue is
        # empty, so "this window deferred and found nothing" is on disk and cannot be
        # confused with "this window was never confirmed".
        queue_path = paths.redos_queue_path(win_lo, win_hi)
        queue = _build_redos_queue(redos_candidates, patterns, config, versions, prov,
                                   (win_lo, win_hi))
        _atomic_write_json(queue_path, queue)
        redos = {"deferred": True, "candidates": len(redos_candidates),
                 "confirmed": [], "load_artifacts": 0, "unmeasured": 0,
                 "queue_path": queue_path}
        print(f"\n=== ReDoS confirm DEFERRED: {len(redos_candidates)} candidate(s) "
              f"queued, not measured ===", flush=True)
        print(f"    -> {queue_path}", flush=True)
        if queue["harnesses_missing"]:
            print(f"    [warn] {queue['harnesses_missing']} candidate(s) had no "
                  f"readable harness source and are queued as pointers only",
                  flush=True)
        print(f"    serial confirm would have cost up to "
              f"{len(redos_candidates) * len(config.engines) * HARNESS_TIMEOUT_S}s "
              f"on this box", flush=True)
    else:
        if redos_candidates:
            # Worst case = every candidate timing out on every engine. Stated up front
            # because this phase is serial and pays the full budget per timed-out engine:
            # without a number here, a legitimate multi-minute stretch of timeouts is
            # indistinguishable from a hang.
            worst_s = len(redos_candidates) * len(config.engines) * HARNESS_TIMEOUT_S
            print(f"\n=== ReDoS confirm: re-executing {len(redos_candidates)} candidate(s) "
                  f"serially (>{config.redos_slow_ms}ms under load) ===", flush=True)
            print(f"    worst case {worst_s}s ({len(config.engines)} engines x "
                  f"{HARNESS_TIMEOUT_S}s each); heartbeat every {_CONFIRM_HEARTBEAT_S}s",
                  flush=True)
            redos = _confirm_redos(redos_candidates, patterns, config)
        redos_path = paths.redos_report_path(win_lo, win_hi)
        _atomic_write_json(redos_path, {
            "window": {"start": win_lo, "end": win_hi},
            "engine_versions": versions, "provenance": prov,
            "slow_ms": config.redos_slow_ms, "engine_ratio": config.redos_engine_ratio,
            "caveat": ("confirmed = engine-specific slowness, NOT proven ReDoS: these are "
                       "unrelated fuzz strings, not one shape at growing lengths, so no "
                       "superlinear scaling was measured"),
            **redos,
        })
    headline = _build_headline(versions, n_items, n_items, n_total,
                               totals, discrepancy_index, cache, prov, (win_lo, win_hi),
                               redos=redos)
    _atomic_write_json(headline_path, headline)

    print("\n" + "=" * 60)
    print(f"cases run:            {totals['cases']}")
    print(f"VALUE DISCREPANCIES:  {totals['value_discrepancies']}")
    print(f"run defects:          {totals['defect_cases']}   [harness malfunctioned]")
    print(f"engine timeouts:      {totals['timeout_cases']}   [engine blew "
          f"{HARNESS_TIMEOUT_S}s; disjoint from defects -- see redos below]")
    print(f"diffs reused/computed: {cache['reused']}/{cache['computed']}")
    if redos.get("deferred"):
        print(f"ReDoS candidates:     {redos['candidates']} "
              f"(DEFERRED -- nominated under load, NOT confirmed; no findings here)")
    else:
        n_meas = sum(1 for c in redos["confirmed"] if c.get("engine_specific_measured"))
        n_lb = sum(1 for c in redos["confirmed"] if c.get("engine_specific_lower_bound"))
        n_unres = sum(1 for c in redos["confirmed"]
                      if c.get("ratio_censored") and not c["engine_specific"])
        print(f"ReDoS candidates:     {redos['candidates']} "
              f"(confirmed {len(redos['confirmed'])}, of which engine-specific "
              f"{n_meas} measured + {n_lb} lower-bound-only; {n_unres} unresolved "
              f"[censored under the gate]; {redos['load_artifacts']} were load artifacts)")
    print(f"headline -> {headline_path}")
    if redos.get("deferred"):
        print(f"redos queue -> {queue_path}   [NOMINATIONS ONLY -- confirm serially "
              f"on a quiet box before reading anything here as a finding]")
    elif redos["confirmed"]:
        print(f"redos    -> {redos_path}   [engine-specific slowness, NOT proven "
              f"ReDoS -- no length scaling measured]")
    if discrepancy_index:
        print("\ndiscrepancies:")
        for d in discrepancy_index:
            tag = d["flags"] or "none"
            print(f"  {d['regex_id']} {d['api']} #{d['n']} [{tag}]  "
                  f"-> results/{d['regex_id']}/{d['api']}.diff.json")
    print("=" * 60)
    return headline


def main() -> None:
    ap = argparse.ArgumentParser(description="Differential eval over a corpus slice.")
    ap.add_argument("--skip-generate", action="store_true",
                    help="reuse existing artifacts + this window's run record instead "
                         "of regenerating")
    ap.add_argument("--record", default=None,
                    help="explicit run record path (default: the record for this "
                         "window, results/run_record_<start>_<start+limit>.json). Use "
                         "for a merged/rebuilt record whose window is not a first-N "
                         "slice.")
    ap.add_argument("--resume", action="store_true",
                    help="reuse existing per-(regex,api) diff.json whose provenance + "
                         "engine versions match this run; recompute everything else")
    ap.add_argument("--limit", type=int, default=None,
                    help="window size: number of corpus rows to process (default: config.eval_slice)")
    ap.add_argument("--start", type=int, default=0,
                    help="global corpus offset for the window (default: 0). Rows "
                         "[start, start+limit) are processed; ids stay regex_<global index>, "
                         "so a windowed run over NEW rows never re-touches earlier ones.")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4,
                    help="parallel worker threads for engine execution (default: core "
                         "count). NOT part of provenance -- it changes wall-clock, never "
                         "results. Keep <= cores so load can't fake timeout defects.")
    ap.add_argument("--config", default=None, help="path to a config YAML")
    ap.add_argument("--redos-defer", action="store_true",
                    help="do NOT run the serial ReDoS confirm phase; write the "
                         "nominated candidates (with their harness source inlined) to "
                         "results/redos_queue_<window>.json for confirmation later, "
                         "on a quiet box. The confirm phase is single-threaded and "
                         "dominated recent runs -- 6h57m of a 17h18m window -- so "
                         "deferring it buys corpus coverage. NOT part of provenance: "
                         "it changes what this box measures, never what it computes.")
    args = ap.parse_args()
    config = load_config(args.config)
    run_eval(config, generate=not args.skip_generate, limit=args.limit,
             resume=args.resume, workers=args.workers, start=args.start,
             record_path=args.record, redos_defer=args.redos_defer)


if __name__ == "__main__":
    main()
