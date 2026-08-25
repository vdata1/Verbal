# ReDoS nomination by growth-curve fitting — prototype + first full-corpus result

**Prepared:** 2026-07-17, image `verbal:d1f3125`. Prototype: `nominate_probe.py`
(+ `ladder_harness.js`). Evidence: `full_run_node_output.txt` (node, whole 6000–9999
window), `diagnose3.py` / `diagnose3_output.txt` (the three known-pathological rows).

## The idea

Nominate ReDoS-prone regexes without ever running a big string. For each regex: take a
chaos mutant (non-matching, so it forces the full backtracking search), derive a length
**family** by middle-deletion, sweep it from tiny n, fit `log t ~ n` (exponential) vs
`log t ~ log n` (polynomial), classify. The whole thing lives in the cheap regime — no
input here costs more than a few ms — because 2ⁿ explodes so fast the measurable band is
always at small n. Method validated in `../notable_results/node_redos/micro_probe.py`
(recovers base 2.00 on `/(a+)+$/`, φ=1.618 on `/(a|aa)+$/`, k≈2 on `/a+b/`).

## What the first full-corpus run establishes

Ran over all 3,761 `test` regexes of the 6000–9999 window, node only, ~13 min:

```
swept 3525;  skipped 145 (pattern not python-compilable), 91 (chaos made no non-matcher)
verdicts:  SAFE 3333   POLYNOMIAL 48   UNCLASSIFIED 140   EXPONENTIAL 2   LINEAR 1   ERROR 1
oracle SIGALRM timeouts: 8 mutants across 3 regexes
```

**Update 2026-07-17 — all three gaps below are now closed.** The three fixes landed
(`classify()` poly-degree disambiguation + EXPONENTIAL absolute-cost floor;
`ladder_harness.js` per-rung worker bound → HANG verdict). Re-run, same 3525 swept:

```
verdicts:  SAFE 3330   POLYNOMIAL 49   UNCLASSIFIED 140   EXPONENTIAL 3   LINEAR 2   HANG 1
```

The 2 EXPONENTIALs were false (8206, 8848 → now non-exponential); the 3 now are all
real: `regex_6580` (k=10.5), `regex_9577` (k=17.4), and — newly surfaced from
UNCLASSIFIED — `regex_8478` `/(<version>)((\d|\w|[-]|\S)*)</version>/` (k=19.9). `ERROR 1`
(regex_7984) → `HANG 1`, detected in ~1s instead of wedging to the 120s outer timeout.
The POLYNOMIAL/UNCLASSIFIED buckets are preserved by design (see below). Validated
end-to-end against the recorded curves in `dev_validate.py` (9/9: 5 targets + 4 controls).

**Two things work, and they are the load-bearing two.**

1. **The oracle bound is essential and correct.** The "does this mutant match" oracle is
   Python's `re`, itself a backtracking engine, so a pathological non-matching mutant
   makes `re.search` blow up *in-process*, where the sweep's subprocess timeout cannot
   reach it. The unbounded first run wedged one core for **3 hours**. The three regexes
   that did it — `regex_6580` (`#define\s+(\S+)+\s+(\S+)`, the same row
   [`930c43b`](../HANDOFF_redos_timing.md)'s generate oracle was bounded for),
   `regex_7984` (email), `regex_9577` (`^(\.?\w+)*$`) — are exactly the ones worth
   flagging. A SIGALRM bound turns the wedge into signal: a timed-out mutant is a proven
   pathological non-matcher, promoted to the front of the seed queue.

2. **Middle-deletion preserves the pathology on real corpus regexes.** This was the open
   worry, and it is answered: on both engines the derived ladder is a clean exponential
   (`diagnose3_output.txt`).

   ```
   regex_6580 node:  (24,35µs) (27,69µs) (29,280µs) (31,1113µs) (34,8803µs)
   regex_9577 node:  (28,75µs) (31,600µs) (34,1295µs) (37,2805µs) (40,20883µs)
   ```

   No pump identification, no grammar — the ladder over a 57/67-char random fuzzer-shaped
   seed reproduces the blowup.

## The three gaps — what they were and how each was fixed

**All three proven-pathological regexes were mis-verdicted**, each for a different reason.
None was a method failure; all three were prototype robustness gaps. All three are fixed;
each fix is recorded with the discriminant that actually separated the real curves (from
`dev_capture.py` → `dev_curves.json`), not the one first guessed at.

- **`regex_6580`, `regex_9577` → UNCLASSIFIED → now EXPONENTIAL.** The curves ARE
  exponential, but the middle-deletion ladder over a heterogeneous 57/67-char corpus seed
  *wobbles the exponent* (different chars leave at each rung), pulling exp R² down to ~0.96
  and letting a high-degree polynomial edge out R² while needing k > 6. Both gates missed.
  **The fix is a poly-degree disambiguation, NOT the knee logic first proposed here.** The
  captured curves killed the knee idea: 9577's real curve is non-monotone (len-34 drops
  below len-33), so a "longest-clean-exponential-prefix" scan returns 0 clean points on it.
  What separates cleanly is the *fitted polynomial degree*: every true exponential forces
  k > 8 (6580: 10, 9577: 17, 8478: 20, controls: 8–11), while real polynomials sit at
  k ≈ 2. So `classify()` now promotes to EXPONENTIAL when the exp fit is decent
  (R² ≥ `EXP_R2_MIN` 0.95, base ≥ 1.1) AND the only competing poly needs an absurd degree
  (k > `POLY_K_MAX` 6) — "an exponential masquerading as a high-degree power law." Real
  polynomials (k ≤ 6) never trip it, so the POLYNOMIAL bucket is untouched.

- **`regex_7984` → ERROR → now HANG.** node *itself* backtracks catastrophically on one
  rung; `perCall` ran `test()` to completion before checking `STOP_MS`, and `re.test()` is
  synchronous and uninterruptible **in-thread**, so no in-thread timer could bound it — the
  oracle-unboundedness lesson one level down. **The fix runs the timing in a worker thread
  with the main thread as a watchdog**: a rung that runs past `PER_RUNG_MS` (1000ms) with
  no progress → `worker.terminate()` (verified to actually interrupt a running native
  regex on V8/node 26) → report `{hung, hung_len}`. `classify()` short-circuits that to a
  `HANG` verdict — an engine that wedges on a 52-char input is the strongest signal there
  is. 7984 now resolves in ~1s. (node/bun take the bounded worker path; deno keeps the
  legacy inline path, where a hang still falls to the outer timeout — deno isn't in the
  corpus run.)

- **The 2 EXPONENTIAL verdicts were FALSE POSITIVES → now non-exponential.** `regex_8206`
  (`.*yaml-tests…`) and `regex_8848` (`^([^.]+).([^.]+)$`) fit `base ≈ 1.10` at
  `dearest 0.001ms` — the sweep never cleared the noise floor and the classifier fit timer
  jitter. **The fix is an absolute cost floor on the EXPONENTIAL verdict only**
  (`ABS_FLOOR_MS` 1ms on the dearest measured rung) on top of the 10×-call-overhead
  relative floor. It is deliberately NOT global: the corpus data shows *all 49* POLYNOMIAL
  nominations peak sub-10µs (median 0.000ms, max 0.010ms), so a global 1ms floor would
  delete the entire bucket. The exponentials, by contrast, cross the floor decisively
  (5–9ms), so it gates them cleanly. 8206 now reads UNCLASSIFIED, 8848 POLYNOMIAL — both
  honest untriaged buckets, neither a false exponential.

## Status: fixed (see the run-2 verdict block above)

All three landed in `classify()` (`nominate_probe.py`) and `ladder_harness.js`, validated
9/9 by `dev_validate.py`. The SAFE=3330 count now means "3,330 not super-linear on node."

**One caveat the fixes surface rather than solve:** every POLYNOMIAL/UNCLASSIFIED
nomination peaks sub-10µs, so at nominate-time they cannot be told apart from fit-noise —
a real cheap O(n²) at 40 chars is *also* sub-10µs. That is a confirm-phase question (run a
longer input), not a classify one; 8848-as-POLYNOMIAL is representative, not an outlier. If
those buckets ever need to be trusted without a confirm pass, they'd want their own floor.
The 48/49 POLYNOMIAL verdicts (k≈2 on `.*x.*`-shaped patterns) look plausible and are the most
interesting untriaged bucket: super-linear-but-not-exponential is real ReDoS the yes/no
framing misses.

## Uniformity / provenance notes

Seed selection is uniform (prefer oracle-timed-out mutants, then longest — no per-regex
branching). The Python `re` oracle is a prototype stand-in for the pipeline's recorded
`py_re_matches`; 145 JS-only patterns skip it and are counted, not hidden. A real
integration would reuse the transpiler's oracle and run under the pool's provenance.
