# Handoff — the ReDoS timing tracker: what landed, and the three calls left open

> **Resolved 2026-07-17 (`52632d2`, `9919668`, `e283381`, `edbe454`).** All three calls
> are closed — read [the resolutions](#resolved) before acting on
> §"[The three calls](#calls)": one prescribed a fix that does not work, and another was
> already done when it was written.
>
> **This document's central claim is RETRACTED.** "bun does not blow up" is wrong: bun
> is exponential at base 2.00, the same as node and deno, and its 686ms is the plateau
> of a **step cap** — the engine giving up, not the engine coping. Worse, past that cap
> bun returns a **wrong value**, fast: that is now
> [F004](differential_findings/DISCREPANCIES.md#f004). See [R5](#r5).
>
> The "real next step" below still gates any ReDoS claim, but its diagnosis is also
> wrong — length was never the problem ([R4](#r4)). Every *measurement* here reproduces;
> what changed is what several of them mean.

**Status:** both commits are on `repo-reorg`, working tree clean, smoke passing at
HEAD **and** at the intermediate commit. Nothing is half-finished.
**Prepared:** 2026-07-17. **Image:** `verbal:d1f3125`. **Branch:** `repo-reorg`.

This picks up a session that disconnected mid-work. The changes were recovered from
the working tree, verified, and split into two commits. Nothing was lost — the split
was checked file-by-file against a pre-split backup.

---

## TL;DR

| Commit | What |
|--------|------|
| `930c43b` | `generate:` bound the neutral oracle so a backtracking regex can't wedge a run |
| `6f7f3d2` | `eval:` in-harness `exec_ms` + a ReDoS candidate tracker with a serial confirm phase |
| `52632d2` | `eval:` split engine timeouts out of run defects ([R1](#r1), [R2](#r2)) |
| `9919668` | `eval:` heartbeat + worst-case banner for the serial confirm phase ([R3](#r3)) |

All four were verified by driving the real behaviour, not just by running the smoke
test (which passes but reaches neither interesting path — it found 0 candidates and 0
oracle timeouts). The first two commits' probes are reproduced verbatim below, because
they lived in a session scratchpad that is now gone; the last two's are described in
[Resolutions](#resolved) on the same reasoning.

---

## What was actually measured

### The oracle fix (`930c43b`)

Against the real hang (`#define\s+(\S+)+\s+(\S+)`, corpus row 6580), `config/smoke.yaml`,
6s budget:

```
counts   = [1, None]
elapsed  = 6.0s          (was: unbounded — it spun a chunk at 100% CPU for hours)
```

The fast string's count survives the SIGKILL (streaming pays off), and the
pathological one is `None` → `py_re_matches: null`, **not `0`**. That distinction is
the entire point: `0` is the miscompilation signal, so reading `null` as `0` would
manufacture a miscompilation out of a timeout.

### The tracker (`6f7f3d2`)

Against `/(a+)+$/` vs `"a"*31 + "!"`, all three engines, unloaded:

```
_engine_ms            = {bun: 686}      <- the ONLY engine that reports a number
_timed_out_engines    = [deno, node]    <- both V8, killed at HARNESS_TIMEOUT_S=20
nominated by exec_ms  = False           <- 686ms is UNDER the 1000ms threshold
nominated by timeout  = True
CONFIRMED ENGINE-SPECIFIC  deno=20000ms bun=680ms (29.4x) [>= bound]
```

**This is the design's central claim, and it held exactly.** Timing alone nominates
*nothing* here. Only the timeout trigger catches it. If you ever find yourself
"simplifying" `_timed_out_engines` away because `exec_ms` seems to cover it, this is
the counterexample — re-run the probe before touching it.

> **RETRACTED — see [R5](#r5).** The measurement above is real and reproduces; the
> reading of it is wrong. `686` is not bun coping with the regex, it is bun's step
> budget running out. bun is exponential at base 2.00 exactly like V8. The `29.4x` is
> V8-unbounded against JSC-capped — a constant factor between two base-2 engines, not
> an algorithmic difference. And the timeout trigger is not the sound half either: it
> **can never fire for bun on this class**, because bun caps instead of timing out.

### One figure that did NOT reproduce

The drafted docstrings said node 76s / deno 73s. This host measured **186s / 149s**.
Same shape, different numbers — a V8 exponential blowup is machine-dependent. The
committed text now cites one host and leans on the *ratio*, not the seconds.
**bun's 686ms reproduced to the millisecond**, which is decent evidence the
disconnected session really did run this rather than drafting from memory.

---

## The three calls, as they were left open {#calls}

*All three are now closed — [Resolutions](#resolved) records what each turned out to
be. Kept as written, because two of them were wrong in ways worth seeing.*

### 1. Every ReDoS finding double-counts as a run defect (confirmed, not suspected)

> **CLOSED (`52632d2`) — and the fix below is wrong. See [R1](#r1).**

`run_engine` sets `defect = timed_out or ...` (eval/run_eval.py:129), and `_tally` has
an unconditional `if c["any_defect"]` — not an `elif`. The probe printed
`any_defect = True` for `/(a+)+$/`. So your sharpest results land in `defect_cases`
and print `! DEFECT node:None/TO deno:None/TO bun:0`, where they read as run
*infrastructure failures* rather than results.

Arguably wrong: nothing defected, the engine did exactly what we were probing for.
Arguably fine: the harness genuinely failed to deliver a canonical line. It's a
judgment call about what `defect` means, which is why it was left alone rather than
decided mid-commit. One-word fix either way (`if` → `elif`, or drop `timed_out` from
`defect`). **Decide before the next full-corpus run**, or the headline's defect count
will need explaining after the fact.

### 2. There is no G8 — and the design guidance lives only in a commit message

> **CLOSED (`52632d2`), mostly as already-done. See [R2](#r2).**

`EXPERIMENT_GAPS.md` has **G1–G7 only**. The ReDoS gap is a one-liner under the
*expansion surface* ("5. Timing/ReDoS"), which the doc explicitly frames as *"coverage
we have never had, as opposed to coverage we are losing"* — a different category from
a gap. `6f7f3d2` expanded that one-liner accordingly.

But `db99701`'s **commit message** contains a detailed "G8" entry that was never
written into the file, and it prescribed this implementation almost to the letter
("Measure in-harness, as node_redos/ already does, and keep it out of `_comparable()`",
plus the startup figures node 30ms / bun 14ms / deno 20ms). That guidance is good and
currently discoverable only via `git log -S`. **Worth promoting into the doc** — either
as a real G8 or folded into the expansion item. Flagging it because an earlier read of
this repo mistook that commit body for the file's contents; the file is the source of
truth.

### 3. The confirm phase has no heartbeat and pays full timeout cost

> **CLOSED (`9919668`) — built as described. See [R3](#r3).**

`_confirm_redos` re-runs each candidate through every engine at up to 20s. A case
where node and deno both time out costs ~40s, serially, after the pool drains. Correct
for measurement fidelity, but a full-corpus run nominating a few hundred candidates
gives a long tail phase that prints only per *confirmed* case — a stretch of timeouts
looks exactly like a hang. Consider a heartbeat, or a worst-case duration in the phase
banner.

---

## Resolutions — 2026-07-17 {#resolved}

All three closed in one session. Two of the three were not what this document said
they were, which is the part worth reading.

### R1 — the "one-word fix" does not exist {#r1}

Above: *"One-word fix either way (`if` → `elif`, or drop `timed_out` from `defect`)."*
**Neither works.** The diagnosis was right, which is exactly what made this easy to
wave through:

- `defect = timed_out or exit_code not in (0,) or canonical is None`. A timed-out
  engine trips **all three** disjuncts on its own — `exit_code` is `None`, and the
  harness prints its envelope only *after* the api call returns, so `canonical` is
  `None` too. Dropping `timed_out or` changes nothing.
- `if` → `elif` chains `any_defect` to `value_discrepancy`. For a ReDoS case only bun
  produces a comparable, so `value_discrepancy` is `False` and the `elif` still fires.
  Also nothing.

So `timed_out` has to **suppress** `defect`, not be dropped from it. Settled the
judgment call the doc left open by splitting the two into disjoint classes:
`defect_cases` now means only "the harness malfunctioned", and `timeout_cases` is its
own axis. Probed against a real harness — `node` on `while(true){}` reports
`exit=None canonical=None` (both disjuncts primed) and `defect=False`.

One thing this document did not anticipate: `--resume` would have skewed silently.
Every diff.json written before `52632d2` recorded `defect: true` on a timed-out run,
so an old artifact would tally differently from a fresh one — breaking the uniformity
`_tally`'s docstring promises. `_outcome()` derives both counters from the per-run
`timed_out` field (always recorded) rather than the stored `any_defect`, so old and
new records agree.

### R2 — the guidance was already promoted {#r2}

Above: *"that guidance ... [is] currently discoverable only via `git log -S`"*.
Not so — `6f7f3d2` promoted it when it expanded the *Timing/ReDoS* item, as this
document itself notes one sentence earlier. Checked line by line against
`db99701`'s body: the startup figures (node 30ms / bun 14ms / deno 20ms), "keep it
out of `_comparable()`", "measure in-harness as `node_redos/` does", and
G7-gates-it are **all** in `EXPERIMENT_GAPS.md:634-661` already.

What was left was stale rather than missing: `db99701` says *"no timing is
recorded"* and leans on `defect_cases: 0`, both overtaken by `6f7f3d2` and R1.

**No G8 was created**, deliberately. It would duplicate the expansion item, and it
would cut against the doc's own taxonomy: G-numbers are for *coverage we are losing*,
while the expansion surface is *coverage we never had* — which is where ReDoS sits.
The one edit made is the piece that was both missing and not stale: how to read a
zero, now that `timeout_cases: 0` (not `defect_cases: 0`) is what means "nothing
crossed 20s" — and still not "no ReDoS".

### R3 — heartbeat, built as described {#r3}

A 30s silence bound plus the worst-case duration in the banner, both suggested
above. Any real verdict line postpones the next heartbeat, so a phase that is
talking stays quiet. Load artifacts are the case that needed it — they return
without printing at all.

### R5 — bun does blow up; 686ms is a step cap, and past it bun is WRONG {#r5}

This document turns on bun being the engine that reports a number where V8 hangs. A
length sweep says otherwise ([F004](differential_findings/DISCREPANCIES.md#f004)):

```
bun on /(a+)+$/ vs "a"*n+"!":
  (17,1.81ms) (19,7.17ms) (21,28.62ms) (23,111.91ms) (25,460.29ms)   <- base 2.00, R2=1.0000
  (27,673ms) (29,682) (31,669) (33,682) (35,684) (37,678) (40,682)   <- FLAT
```

bun is exponential at **base 2.00** — node 1.991, deno 2.001. It does not handle the
regex; it stops searching. The plateau is a **step** budget, not a clock: bun plateaus
at ~678ms on `/(a+)+$/` but ~1780ms on `regex_3910`, whose inner loop is costlier. So
the crossover n is host-independent and reproducible; only the wall-clock is this host's.

**686ms is that plateau.** This document reads its exact reproducibility as evidence the
disconnected session honestly ran the probe. It reproduces to the millisecond because a
budget being spent is deterministic in a way that work being measured is not. The
inference was reasonable and the conclusion was backwards.

**And the cap is unsound.** `/(a+)+$/.test("a".repeat(26) + "!aaa")` is `true` — the
regex is unanchored, so it matches the trailing `aaa`. node and deno return `true` (8.8s,
7.0s). bun returns **`false` in 679ms**, out to n=100. No timeout; all three engines run
clean. It is a plain value discrepancy, and `_comparable()` would catch it today if a run
ever produced the input.

Two consequences for the design here:

- **The timeout trigger — this document's "load-bearing half" — can never fire for bun
  on this class.** bun caps rather than timing out. The tracker is blind to JSC's most
  interesting behaviour by construction, and no amount of tuning `redos_slow_ms` helps.
- **`engine_specific` at 29.4x is not an algorithmic finding.** It is V8-unbounded vs
  JSC-capped: a constant factor between two engines that are both base 2.

What survives: keeping `exec_ms` out of `_comparable()`, the oracle bound, and the
instinct that `_timed_out_engines` sees something `exec_ms` cannot. What does not: the
belief that a timeout is the *sharpest* signal. The sharpest signal was a wrong answer
returned in 679ms, which no timing oracle can see.

### What verified this

The smoke test still reaches **none** of these paths (0 candidates, 0 timeouts), so
it is no more a verification than it was for the original commits. Two probes did the
work, in a scratchpad, unpreserved on the same reasoning as the originals — R1's is
reproducible from its description above; R3's stubs `_diff_one` with three candidate
shapes (load artifact / confirmed-via-timeout / unmeasured) and forces
`_CONFIRM_HEARTBEAT_S = 0`. R3's probe re-derived **node=20000ms bun=686ms, 29.2x**
against the 29.4x recorded above — the same lower bound, off only by this document's
rounding of bun to 680ms in one line and 686ms in another.

---

## The real next step (unchanged, and it gates the headline claim)

> **Superseded 2026-07-17 (`edbe454`) — the diagnosis below is wrong on both counts.**
> "Fixed-length fuzz strings" is not what the fuzzer produces (p50 21 chars, p90 60,
> max 285), and "emit inputs at growing lengths" is not what closing this needs. See
> [R4](#r4). The conclusion — do not call a confirmed case ReDoS — still stands.

**None of this proves ReDoS**, and both the artifact's `caveat` field and the doc say
so. Catastrophic backtracking means runtime growing *superlinearly in input length*;
these are fixed-length fuzz strings, so there is no length axis to measure along. What
is confirmed is **engine-specific slowness**.

Closing it needs the fuzzer to emit inputs at **growing lengths** so a scaling curve
exists. `chaos` (`d1f3125`) is the natural home: a ReDoS input *is* a boundary input —
non-matching, which is exactly what forces the full exponential search. That is also
the same mechanism that made the oracle hang reachable in the first place, so the two
halves of this work are really one story.

Until that lands, do not describe a confirmed case as ReDoS in any write-up.

### R4 — length was never the problem {#r4}

Measured over the 6000–9999 window's 49,733 `test` strings: **p50 21 chars, p90 60,
p99 111, max 285.** 61% of regexes have a string ≥20 chars; 45% have one ≥26. The
fuzzer emits long strings and always did.

The real gap is that its ~20 strings per regex are **unrelated**, and a growth curve
cannot be fitted across strings that share no shape — each has its own constant factor.
The missing thing is a length **family**: one shape at growing n. That is structural
and cheap, not a magnitude problem needing grammar work.

It is closed by *deriving* a ladder from a string already emitted. A middle-deletion
ladder over `regex_3910`'s raw 65-char fuzzer string recovers base 1.989 (R² 0.9999)
with no pump identification. And no long execution is needed anywhere:
`notable_results/node_redos/micro_probe.py` classifies `regex_3910` from a **24-char**
input in milliseconds, and recovers φ=1.618 on `/(a|aa)+$/`.

`chaos` is still the right home, and this section was right about *why*: the ladder
needs a **non-matching** seed to force the full search. The same regex on a matching
input is measurably free — `/(a+)+$/` on `"a"*n` is flat at 0.05µs out to n=40.

The work that came out of this: [F004](differential_findings/DISCREPANCIES.md#f004) —
bun abandons backtracking at a step budget and returns a **wrong value**, fast. Which
reframes the whole effort: length is the axis along which engines cross their internal
limits, and crossing one produces a discrepancy, not just a slow case. It also retracts
this document's central claim — bun is exponential at base 2.00 like V8, and its 686ms
is the plateau of a step cap, not evidence it handles the regex well.

---

## Reproducers (run verbatim; both were run as written)

Mount the repo at `/repo`, **not** `/app` — mounting over `/app` hides the image's
`.engine-pins.json` and the entrypoint's version assert dies.

**Smoke (passes, but reaches neither new path — don't mistake it for verification):**

```bash
docker run --rm -v /home/turcotte/projects/verbal:/repo \
  verbal:d1f3125 bash /repo/tests/new_pipeline_smoke.sh
```

**The oracle bound** — save as `oracle_probe.py`, mount at `/probe`:

```python
import sys, time
sys.path.insert(0, "/repo"); sys.path.insert(0, "/repo/src")
from src.pipeline.config import load_config
from src.pipeline import generate

cfg = load_config("/repo/config/smoke.yaml")
pattern = r"#define\s+(\S+)+\s+(\S+)"          # corpus row 6580, the real hang
strings = ["#define A B", "#define " + "x" * 40 + "!"]   # [0] matches, [1] wedges

t0 = time.monotonic()
counts = generate._neutral_match_counts(pattern, strings, "", "regex_6580", "test", cfg)
print("counts =", counts, "elapsed = %.1fs" % (time.monotonic() - t0))
assert counts[0] == 1 and counts[1] is None    # null, NOT 0
```

```bash
docker run --rm -v /home/turcotte/projects/verbal:/repo -v "$PWD":/probe \
  verbal:d1f3125 python3 /probe/oracle_probe.py
```

**The engine split, raw** (no pipeline involved — `node` takes ~3min, `deno` ~2.5min,
`bun` returns instantly; that asymmetry *is* the finding):

```js
// redos_probe.js
const re = new RegExp("(a+)+$", "");
const s = "a".repeat(31) + "!";
const t0 = performance.now();
const v = re.test(s);
console.log(JSON.stringify({value: v, exec_ms: performance.now() - t0}));
```

```bash
for e in node bun deno; do
  docker run --rm -v "$PWD":/probe verbal:d1f3125 bash -c "cd /probe && $e redos_probe.js"
done
```

**The full confirm phase** — the probe that drove `_diff_one` → `_engine_ms` →
`_timed_out_engines` → `_confirm_redos` end-to-end is not preserved; rebuild it by
synthesizing a harness with
`generate.synthesize_harness(DESCRIPTORS_BY_API["test"], "(a+)+$", "", "a"*31+"!", rid, cfg)`,
writing it to `paths.api_harness_path(rid, "test", 0, "")`, then calling
`run_eval._confirm_redos([...], {rid: pattern}, cfg)`. Two gotchas that cost time:
`DESCRIPTORS` is a **tuple** (use `DESCRIPTORS_BY_API`), and `provenance()` hashes
`config.corpus_path`, so `data/uniq-regexes-sample.json` must exist under the temp
root.
