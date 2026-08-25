"""Dev-only: the CONFIRM pass over the POLYNOMIAL / UNCLASSIFIED nominees.

Nominate keeps every candidate in the cheap regime -- no input it runs costs more than a
few ms -- which is exactly what makes it safe to sweep corpus-wide. It is also why every
POLYNOMIAL / UNCLASSIFIED verdict peaks sub-10us: at a ~40-char seed length a real cheap
O(n^2) is indistinguishable from timer noise, and the classifier says so. This pass
resolves that the only honest way it can be resolved -- run ONE genuinely long input per
nominee and watch the cost -- for the 49+140 candidates the corpus run produces, few
enough to run serially (HANDOFF_2026-07-17).

Two-phase by design: nominate --dump-nominees writes the shortlist (rid + seed + verdict
+ pattern); this consumes it, so the expensive bounded-oracle seed derivation is not
redone. EXPONENTIAL / HANG nominees are already confirmed by nominate's absolute-cost
floor / worker bound and pass straight through; only POLYNOMIAL / UNCLASSIFIED get a long
run.

Per POLYNOMIAL/UNCLASSIFIED nominee:
  1. Grow the SAME seed to a geometric length ladder by MIDDLE-PUMP: repeat the seed's
     interior, keeping both ends intact. The exact inverse of the middle-DELETION that
     built the nominate ladder -- same "no pump identification, preserve the ends that
     force the failure" bet, run upward instead of down.
  2. A bounded Python-re oracle (the same discipline as nominate) drops any pumped input
     that now MATCHES: a matching input never backtracks, its cost collapses, and it is
     not evidence. An input that TIMES OUT the oracle is non-matching AND already
     pathological for one backtracking engine -- kept, and a strong prior.
  3. Sweep the surviving long inputs in the worker-bounded harness with a REAL budget
     (stop_ms 50, per_rung_ms 3000). A rung that hangs the engine -> CONFIRMED outright.
  4. CONFIRMED iff the deepest non-matching rung clears CONFIRM_FLOOR_MS AND the growth is
     super-linear (fitted poly k >= K_MIN, or an endpoint exponent when the band is
     sparse). DROPPED otherwise: either it never left the noise floor even at n=CAP (the
     verdict really was fit-noise) or it scaled only linearly (a big scan, not ReDoS).

Run inside the container with the tree mounted (node lives there, not on the host):

  docker run --rm -v "$PWD":/work -w /work verbal:latest bash -lc '
    PYTHONPATH=/work/src python3 analysis/redos_nomination/nominate_probe.py \
      --window /work/results-run-6000-9999 --limit 100000 --engines node \
      --dump-nominees /work/analysis/redos_nomination/dev_nominees.jsonl &&
    PYTHONPATH=/work/src python3 analysis/redos_nomination/dev_confirm.py \
      --nominees /work/analysis/redos_nomination/dev_nominees.jsonl --engine node \
      --dump /work/analysis/redos_nomination/dev_confirm_results.json'

Offline plumbing check (no node, host-runnable): python3 dev_confirm.py --check
"""
import argparse
import json
import math
import os
import re
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "ladder_harness.js")
SPEC = "/tmp/confirm_spec.json"
ENGINE_CMD = {"node": ["node"], "bun": ["bun"],
              "deno": ["deno", "run", "--quiet", "--allow-read"]}

ORACLE_MS = 200          # bound on the Python-re non-match check (it, too, backtracks)
CONFIRM_CAP = 4096       # longest input the pump climbs to
CONFIRM_FLOOR_MS = 1.0   # a confirmed cost must clear this at scale -- 100x above the
                         # ~10us nominate noise floor, so timer jitter cannot reach it
CONFIRM_K_MIN = 1.5      # ...and grow super-linearly; a linear scan that clears the floor
                         # is a big-input cost, not backtracking ReDoS
CONFIRM_R2_MIN = 0.90
PER_RUNG_MS = 3000       # worker watchdog: a rung past this -> engine hung -> CONFIRMED
STOP_MS = 50             # stop climbing once a rung is this dear; growth is settled by then


class _OT(Exception):
    pass


signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(_OT()))


def matches_bounded(rx, s):
    """(matched, timed_out). Same bounded oracle as nominate_probe: re backtracks, and a
    long pathological non-matcher blows it up in-process, so SIGALRM bounds it. A timeout
    is non-matching AND proven pathological for one engine."""
    signal.setitimer(signal.ITIMER_REAL, ORACLE_MS / 1000)
    try:
        return bool(rx.search(s)), False
    except _OT:
        return False, True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def mid_resize(seed: str, L: int) -> str:
    """Resize `seed` to length L, preserving BOTH ends. L <= len shrinks by middle
    deletion (nominate's ladder); L > len grows by repeating the interior in the middle --
    the inverse construction. No pump identification: the whole interior run is the pump."""
    n = len(seed)
    if L <= n:
        a, b = (L + 1) // 2, L // 2
        return seed[:a] + (seed[n - b:] if b else "")
    head, tail = seed[:(n + 1) // 2], seed[(n + 1) // 2:]   # partition -> head+tail == seed
    interior = seed[n // 4: n - n // 4] or seed or "a"       # a middle slice to repeat
    need = L - n
    pad = (interior * (need // len(interior) + 1))[:need]
    return head + pad + tail                                 # len == n + need == L


def confirm_lengths(seed_len: int, cap: int = CONFIRM_CAP) -> list:
    """Geometric (base-2) length ladder up to `cap`, anchored at the seed length. Log
    spacing makes a power law a straight line in the log-log fit."""
    xs, L = set(), 64
    while L <= cap:
        xs.add(L)
        L *= 2
    xs.add(cap)
    xs.add(max(seed_len, 8))
    return sorted(x for x in xs if x >= 8)


def ols(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    icept = my - slope * mx
    sst = sum((y - my) ** 2 for y in ys)
    ssr = sum((y - (icept + slope * x)) ** 2 for x, y in zip(xs, ys))
    return slope, icept, (1 - ssr / sst if sst > 0 else 1.0)


def sweep(engine, pattern, flags, inputs):
    """One process, the SAME worker-bounded harness nominate uses, but with a real budget:
    long inputs, a 50ms stop and a 3s per-rung worker watchdog (a hung rung is signal)."""
    spec = {"pattern": pattern, "flags": flags, "inputs": inputs,
            "stop_ms": STOP_MS, "per_rung_ms": PER_RUNG_MS, "accum_ms": 2}
    with open(SPEC, "w") as f:
        json.dump(spec, f)
    try:
        p = subprocess.run(ENGINE_CMD[engine] + [HARNESS, SPEC],
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "harness wall-clock"}
    for line in p.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and "ok" in o:
            return o
    return {"ok": False, "error": (p.stderr or "no output").strip()[:160]}


def build_inputs(rx, seed, timed_out_seed=False):
    """Grow the seed along the length ladder and keep only the non-matching rungs -- the
    ones that still force backtracking. Returns (inputs, notes). If the oracle already
    timed out on the seed, skip the per-rung oracle (it would just time out again, slowly)
    and trust the pump: the seed is a proven pathological non-matcher."""
    inputs, dropped_match = [], 0
    for L in confirm_lengths(len(seed)):
        s = mid_resize(seed, L)
        if timed_out_seed:
            inputs.append(s)
            continue
        matched, _ = matches_bounded(rx, s)
        if matched:
            dropped_match += 1
        else:
            inputs.append(s)
    return inputs, {"dropped_match": dropped_match}


def classify_confirm(res, baseline_hint=None):
    """(verdict, detail, evidence). CONFIRMED / DROPPED / ERROR. Works on the non-matching
    rungs only -- a rung the pump accidentally made matchable is not evidence of anything."""
    if not res.get("ok"):
        return "ERROR", res.get("error", "?"), {}
    if res.get("hung"):
        n = res.get("hung_len")
        return ("CONFIRMED", f"engine hangs (>{PER_RUNG_MS}ms) on a {n}-char input -- the "
                f"strongest confirmation there is", {"hung_len": n})
    pts = res.get("points", [])
    nm = [p for p in pts if not p.get("value")]      # non-matching == still backtracking
    if not nm:
        return ("DROPPED", "every long input matched (the pump created a match); the "
                "backtracking path is gone, no evidence either way", {"matched_all": True})
    base = res.get("baseline_ms") or baseline_hint or 0.0
    deep = max(nm, key=lambda p: p["len"])           # deepest non-matching rung we ran
    peak_ms, peak_len = deep["ms"], deep["len"]

    # exponent: OLS over the log-log band where cost cleared 10x call overhead; fall back
    # to the endpoint slope when the band is too sparse to fit (few rungs above the floor).
    usable = [p for p in nm if p["ms"] >= 10 * base] if base else nm
    k = r2 = None
    src = None
    if len(usable) >= 3:
        f = ols([math.log(p["len"]) for p in usable], [math.log(p["ms"]) for p in usable])
        if f:
            k, _, r2 = f[0], f[1], f[2]
            src = "fit"
    if k is None:
        lo = min(nm, key=lambda p: p["len"])
        if lo["ms"] > 0 and deep["len"] > lo["len"]:
            k = math.log(peak_ms / lo["ms"]) / math.log(peak_len / lo["len"])
            src = "endpoints"

    ev = {"peak_ms": peak_ms, "peak_len": peak_len, "k": k, "k_src": src, "r2": r2,
          "n_nonmatching": len(nm)}
    fit_ok = k is not None and k >= CONFIRM_K_MIN and (r2 is None or r2 >= CONFIRM_R2_MIN)
    if peak_ms >= CONFIRM_FLOOR_MS and fit_ok:
        r2s = f" R2 {r2:.3f}" if r2 is not None else ""
        return ("CONFIRMED", f"super-linear at scale: {peak_ms:.1f}ms at n={peak_len}, "
                f"k={k:.2f} ({src}{r2s})", ev)
    if peak_ms >= CONFIRM_FLOOR_MS:
        ks = f"{k:.2f}" if k is not None else "n/a"
        return ("DROPPED", f"clears the floor but grows only ~linearly (k={ks}) -- a big-"
                f"input scan, not backtracking: {peak_ms:.1f}ms at n={peak_len}", ev)
    return ("DROPPED", f"stayed in the noise floor to n={peak_len} "
            f"({peak_ms:.3f}ms < {CONFIRM_FLOOR_MS}ms) -- the nominate verdict was fit-"
            f"noise", ev)


# --------------------------------------------------------------------------------------
def run_check():
    """Offline plumbing check -- pure functions only, no node. Host-runnable."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {msg}")

    s = "ABCdefghijKLM"
    chk(len(mid_resize(s, 5)) == 5 and mid_resize(s, 5)[0] == "A" and mid_resize(s, 5)[-1] == "M",
        "mid_resize shrinks, preserves both ends")
    chk(len(mid_resize(s, 200)) == 200 and mid_resize(s, 200).startswith("ABC")
        and mid_resize(s, 200).endswith("KLM"), "mid_resize grows to exact length, ends intact")
    chk(mid_resize(s, len(s)) == s, "mid_resize is identity at the seed length")
    L = confirm_lengths(40)
    chk(L == sorted(L) and L[-1] == CONFIRM_CAP and all(x >= 8 for x in L),
        f"confirm_lengths monotone, capped at {CONFIRM_CAP}: {L}")

    # synthetic curves through classify_confirm
    def curve(pairs, **kw):
        return {"ok": True, "baseline_ms": 1e-4,
                "points": [{"len": n, "ms": t, "value": False} for n, t in pairs], **kw}

    quad = curve([(64, 0.01), (256, 0.16), (1024, 2.6), (4096, 42.0)])   # ~n^2
    v, d, _ = classify_confirm(quad)
    chk(v == "CONFIRMED", f"quadratic curve -> CONFIRMED ({d})")

    noise = curve([(64, 0.002), (256, 0.003), (1024, 0.004), (4096, 0.006)])
    v, d, _ = classify_confirm(noise)
    chk(v == "DROPPED", f"flat sub-floor curve -> DROPPED ({d})")

    lin = curve([(64, 0.05), (256, 0.2), (1024, 0.8), (4096, 3.2)])       # ~n
    v, d, _ = classify_confirm(lin)
    chk(v == "DROPPED", f"linear-but-over-floor curve -> DROPPED ({d})")

    hung = {"ok": True, "hung": True, "hung_len": 1024, "baseline_ms": 1e-4, "points": []}
    chk(classify_confirm(hung)[0] == "CONFIRMED", "hung engine -> CONFIRMED")

    matched = {"ok": True, "baseline_ms": 1e-4,
               "points": [{"len": 4096, "ms": 0.001, "value": True}]}
    chk(classify_confirm(matched)[0] == "DROPPED", "all-matching rungs -> DROPPED (no evidence)")

    print("\n" + ("ALL PASS" if ok else "!!! SOME FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nominees", help="JSONL from nominate_probe --dump-nominees")
    ap.add_argument("--engine", default="node")
    ap.add_argument("--dump", default=None, help="write confirm results as JSON")
    ap.add_argument("--check", action="store_true", help="offline plumbing check, no node")
    ap.add_argument("--limit", type=int, default=100000)
    args = ap.parse_args()

    if args.check:
        sys.exit(run_check())
    if not args.nominees:
        ap.error("--nominees is required (or use --check)")

    noms = [json.loads(l) for l in open(args.nominees) if l.strip()]
    todo = [n for n in noms if n["verdict"] in ("POLYNOMIAL", "UNCLASSIFIED")][:args.limit]
    passthrough = [n for n in noms if n["verdict"] in ("EXPONENTIAL", "HANG")]

    print("=" * 78)
    print(f"CONFIRM PASS  ({len(todo)} POLYNOMIAL/UNCLASSIFIED to run long inputs; "
          f"{len(passthrough)} EXPONENTIAL/HANG already confirmed by nominate)")
    print(f"engine {args.engine}  cap {CONFIRM_CAP}  floor {CONFIRM_FLOOR_MS}ms  "
          f"k_min {CONFIRM_K_MIN}")
    print("=" * 78)

    results, tally = [], {"CONFIRMED": 0, "DROPPED": 0, "ERROR": 0}
    for i, n in enumerate(todo, 1):
        rx = None
        try:
            rx = re.compile(n["pattern"])
        except re.error:
            pass  # nominees are python-compilable by construction, but never trust that
        # Every pumped rung is oracle-checked for non-match below (bounded), so no need to
        # track the seed's own oracle-timeout provenance here.
        inputs, notes = ([], {"dropped_match": 0}) if rx is None else \
            build_inputs(rx, n["seed"])
        if rx is None or not inputs:
            v, detail, ev = "ERROR", "could not build any non-matching long input", {}
        else:
            v, detail, ev = classify_confirm(sweep(args.engine, n["pattern"], n["flags"], inputs))
        tally[v] = tally.get(v, 0) + 1
        results.append({**{k: n[k] for k in ("rid", "verdict", "pattern", "seed_len")},
                        "nominate_detail": n["detail"], "confirm": v,
                        "confirm_detail": detail, "evidence": ev, "notes": notes})
        print(f"[{i}/{len(todo)}] {v:<9} {n['rid']} (was {n['verdict']}, seed {n['seed_len']})")
        print(f"           /{n['pattern'][:86]}/")
        print(f"           {detail}")

    print("\n" + "=" * 78)
    print(f"CONFIRMED {tally['CONFIRMED']}   DROPPED {tally['DROPPED']}   "
          f"ERROR {tally['ERROR']}   (+ {len(passthrough)} passed through as already-confirmed)")
    conf = [r for r in results if r["confirm"] == "CONFIRMED"]
    if conf:
        print("\nCONFIRMED super-linear (real ReDoS the yes/no framing missed):")
        for r in sorted(conf, key=lambda r: -(r["evidence"].get("peak_ms") or 0)):
            print(f"  {r['rid']} (was {r['verdict']})  /{r['pattern'][:70]}/")
            print(f"      {r['confirm_detail']}")

    if args.dump:
        with open(args.dump, "w") as f:
            json.dump({"confirmed": tally["CONFIRMED"], "dropped": tally["DROPPED"],
                       "error": tally["ERROR"], "passthrough": len(passthrough),
                       "results": results,
                       "passthrough_rids": [p["rid"] for p in passthrough]}, f, indent=1)
        print(f"\nwrote confirm results -> {args.dump}")


if __name__ == "__main__":
    main()
