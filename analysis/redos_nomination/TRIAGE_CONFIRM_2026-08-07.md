# ReDoS confirm triage — windows 12050–15050 and 15050–20035

**Prepared:** 2026-08-11 · **Inputs:** `results/redos_12050_15050.json`, `results/redos_15050_20035.json`
(both `status: complete`, written 2026-08-07 by `eval/confirm_redos.py`) ·
**Method:** §§1–8 are static analysis of the recorded artifacts only — no engine was executed.
§7a additionally runs the native bun binary on this box (bun 1.4.0-canary; node and deno were
unavailable, see §7a). Values cross-referenced against `eval_headline_*.json` and the per-API `<api>.diff.json`
trees under `/scratch/turcotte/verbal/results/`.

> **Headline: the `engine_specific` count is not a finding count. 418 of the 477 flagged rows (88%)
> have a censored slow side, which degenerates the ratio into "did bun finish in under 2 seconds" —
> a threshold on the *fast* engine, not a comparison between two. Once the censored rows are set
> aside, 59 rows carry a real two-sided measurement, and they contain exactly one genuine bug:
> `regex_17570` under the `v` flag, where bun 1.3.14 burns 3.3 s and then returns the **wrong
> answer** while both V8 engines answer correctly in 1.1 ms. That bug is **already fixed in
> bun 1.4.0-canary** (§7a), so this run's net yield of new, live, reportable engine bugs is zero.**

---

## 1. What the confirm pass produced

| | 12050–15050 | 15050–20035 | total |
|---|---:|---:|---:|
| candidates (nominated) | 239 | 975 | 1214 |
| confirmed | 85 | 763 | **848** |
| load artifacts (fast once serial) | 130 | 184 | 314 |
| unmeasured | 24 | 28 | 52 |
| confirm wall-clock | 2 494 s | 29 874 s | 9.0 h |

Gates taken from the queues: `slow_ms = 1000`, `engine_ratio = 10.0`, harness budget **20 000 ms**.
Engines: node v26.5.0, bun 1.3.14, deno 2.9.1 — matching `.engine-pins.json`, so no version drift.

**848 confirmed rows collapse to 9 distinct regexes.** Rows are not findings; the amplification is
94× (848 rows / 9 regexes), worse than the 9.2× the 2026-08-03 nomination triage measured.

The confirm pass did its job as a filter: unlike the raw nomination queue, **all 9 surviving
regexes are structurally capable of superlinear backtracking** — every one has either a quantifier
nested under another or an alternation under a quantifier. The "cannot backtrack at all" bucket
that held 13 of 26 regexes in the nomination queue is empty here.

---

## 2. The censoring defect — why `engine_specific` overcounts

A timed-out engine is scored at the harness budget (`_effective_ms`), and `is_lower_bound` is set.
That is sound bookkeeping. The problem is what it does to the ratio.

When the slow engine is censored at 20 000 ms, `ratio = 20000 / fastest_ms`. The slow side is a
constant. The flag `ratio >= 10` therefore reduces to **`fastest_ms <= 2000`** — a statement about
how fast bun was, containing no information about the engine that timed out.

`regex_14648`, `match`, input #38, shows this directly across flag variants:

| flags | node | deno | bun | ratio | `engine_specific` |
|---|---:|---:|---:|---:|:--:|
| none | 20 000 ✂ | 20 000 ✂ | 1 196 | 16.7 | **true** |
| `d` | 20 000 ✂ | 20 000 ✂ | 1 253 | 16.0 | **true** |
| `g` | 20 000 ✂ | 20 000 ✂ | 6 364 | 3.1 | false |

✂ = censored at the budget. The V8 side is identical in all three rows. The only thing that moved
is bun's own time, and that alone flipped the verdict. Nothing about node or deno was measured.

**Breakdown of the 477 engine-specific rows:**

| | rows | what it is worth |
|---|---:|---|
| slow side censored at the budget | **418** | ratio is a threshold on bun's time; no two-sided reading |
| fully measured, both sides | **59** | a real ratio |

The 418 are not *wrong* — the true ratio is at least what was recorded, since censoring only
understates the slow side. They are **unresolvable at a 20 s budget**, which is a different problem
and needs a longer budget, not a re-reading.

### 2a. The same censoring hides NEGATIVES — and that is the bigger population

Added 2026-08-12. The `g` row above is not just a missing positive: it is recorded as a plain
negative. But node and deno were cut off at 20 000 ms in that row exactly as in the other two, so
nothing about V8 was measured there either. A censored row that lands *under* the gate is not
evidence of "no differential" — it is **unresolved**, and it must not be counted as a negative.

In the 848 rows triaged here that is another **278** rows (24 in `12050-15050`, 254 in
`15050-20035`) on top of the 418.

### 2b. This is not specific to the 2026-08-07 run

The split is recoverable offline from the `serial_ms`/`timed_out` already stored in every artifact,
so all six confirmed windows were reclassified with
`analysis/eval_help_scripts/backfill_ratio_split.py` (2026-08-12). The recomputed union matches the
`engine_specific` on disk for all 2 284 rows, so these are re-readings of the same flag, not a
re-run:

| window | confirmed | flagged | measured | lower bound only | unresolved (censored, under gate) |
|---|---:|---:|---:|---:|---:|
| `6000-10050`  | 397 | 230 | 6 | 224 | 111 |
| `10050-11050` | 478 | 84 | 7 | 77 | 262 |
| `11050-12050` | 561 | 322 | **1** | 321 | 201 |
| `12050-15050` | 85 | 37 | 15 | 22 | 24 |
| `15050-20035` | 763 | 440 | 44 | 396 | 254 |
| **all** | **2 284** | **1 113** | **73** | **1 040** | **852** |

So **93 % of every engine-specific row ever recorded is a censored lower bound**, and the corpus of
genuinely two-sided measurements across all six windows is 73 rows. `11050-12050` produced exactly
one. Any claim resting on a flagged-row count from *any* window needs the measured column, not the
flagged column.

---

## 3. node and deno are the same engine, and the artifact forgets it

On every row where both were measured, node and deno agree within **1.1–1.2×**:

| regex | rows both measured | node/deno ratio (median / max) |
|---|---:|---|
| regex_16710 | 13 | 1.1 / 1.3 |
| regex_16054 | 30 | 1.1 / 1.3 |
| regex_18785 | 20 | 1.1 / 1.2 |
| regex_18808 | 22 | 1.1 / 1.1 |
| regex_14648 | 38 | 1.1 / 1.2 |
| regex_19412 | 14 | 1.2 / 1.2 |
| regex_17797 | 7 | 1.2 / 1.2 |

That is the expected result — both embed V8 — and it means **`slowest_engine` flipping between
`node` and `deno` is measurement noise, not signal.** Any per-regex table that reports "deno was
slowest on 194 rows, node on 13" is reporting scheduling jitter. The real axis is bun vs V8, and on
that axis bun is the fastest engine on **836 of 848 rows**.

---

## 4. The 9 regexes

| regex | rows | eng-spec | two-sided | shape | verdict |
|---|---:|---:|---:|---|---|
| `regex_16710` `^application\/(.*?)+\+json$` | 207 | 145 | 4 | `(.*?)+` | §5 |
| `regex_16054` `^((\w+\s*)+)\n(?:-+\|=+)\n` | 155 | 117 | 15 | `(\w+\s*)+` | §5 |
| `regex_18785` `\A((\w+) ?)+\z` | 144 | 65 | 0 | `((\w+) ?)+` | §5 |
| `regex_18808` `\^{3}math(.*?\n*?)+?\^{3}` | 134 | 54 | 1 | `(.*?\n*?)+?` | §5 |
| `regex_14648` ``^(?:[^`"[]+\|`[^`]*`\|"[^"]*")* AS\s+`` | 84 | 37 | 15 | alternation under `*` | §5 + §6 |
| **`regex_17570`** (URL validator, full text below) | 52 | 14 | 6 | nested `(...)*` | **§7 — real bug, fixed in 1.4.0** |
| `regex_19412` `url\s*\(((?:[^)(]\|\(...\))*)\)` | 44 | 26 | 12 | nested `(...)*` | §5 |
| `regex_17797` (template placeholder) | 27 | 19 | 6 | `(...)+` under alternation | §5 |
| `regex_14841` `(:?0x(?:(?:\d\|[abcdef...]){0,2})+) +in +...` | 1 | 0 | 0 | `(X{0,2})+` | resolved 2026-08-03 §4b |

("two-sided" counts *engine-specific* rows with both sides measured, so it sums to the 59 of §2.
`regex_14841`'s single row is fully measured but was never flagged engine-specific.)

Note `regex_18785` uses `\A` and `\z`, which are **not JavaScript syntax** — in JS they are the
literals `A` and `z`. The pattern is a PCRE/Ruby idiom that landed in a JS corpus. It still
backtracks, so it is a valid stressor, but it is not testing what its author meant.

---

## 5. Why the bulk of it proves nothing — the oracle is blind where it matters

bun being 10–20× faster than V8 looks like a differential until you ask what the two engines
*returned*. bun's known unsound step cap (`analysis/bug_reports/REPORT_bun_backtracking_step_cap.md`,
F004) abandons a long backtrack and reports **no match**. When the true answer is also no-match, bun
is right by accident and fast. That row is the step cap seen from the timing side — not bun
outperforming V8.

Classifying every confirmed row by what was actually recorded:

| | all 848 | of the 477 engine-specific |
|---|---:|---:|
| V8 timed out → **no value to compare** | 696 | 418 |
| both agreed on **no-match** | 118 | 40 |
| both agreed, **a real match was found** | 28 | 13 |
| **values diverged** | 6 | 6 |

The first two rows are the problem:

- **696 rows have no V8 value at all.** The differential oracle needs two values; a timeout yields
  none. For these rows "bun agrees with V8" is not a weaker claim — it is an unmade one. bun could
  be returning a false negative on every one and nothing in this artifact would show it.
- **118 rows agree on no-match**, which is precisely the output an early bailout produces for free.
  Agreement here is consistent with bun being correct *and* with bun capping out. It is not
  evidence either way.

So of 848 confirmed rows, only **34** — the 28 agreements on a real match plus the 6 divergences —
carry a comparison with any power to catch a false negative. On the other 814 an early bailout and a
correct answer are indistinguishable.

---

## 6. The 13 rows where bun is genuinely faster and correct

All on `regex_14648`, all fully measured on both sides, all returning a real match:

```
replace #26 [none,d,g,i,m,s,y]   node/deno 1067–1307 ms   bun 77–84 ms   ratio 13–17
split   #27 [none,d,g,i,m,s]     node      1100–1217 ms   bun 42–53 ms   ratio 21–27
```

This is real: two-sided measurement, a match actually found, bun 13–27× faster with the identical
result. But per the standard this project already set in `HANDOFF_redos_timing.md` R5 and the
2026-08-03 triage §4b — **a constant factor between two engines is not a finding about an engine.**
What would make it one is a different algorithmic class, and that needs a length family (one shape
at growing n), which these unrelated fuzz strings cannot provide. `run_eval._confirm_redos`'s own
docstring says so.

**Not reportable as-is.** It is a good candidate to feed the growth-curve fitter, which is built.

### 6a. Resolved 2026-08-12 — it is a constant factor. Closed.

Fed to the fitter. All four engines (node v26.5.0, deno 2.9.1, bun 1.3.14, bun 1.4.0) are
**exponential in the same variable with base ≈ 2.0** — 32 cells spanning 1.974–2.032, R² ≥ 0.998,
across `test`/`replace`/`split`/`match`. bun is 12–15× cheaper at every length and **the factor does
not grow with n**, which is precisely the discriminator: a class difference would widen it.

So the 13 rows are not a bug in anything, and R5 / §4b apply as written. Full method, controls and
caveats: `GROWTH_14648.md`; data in `growth_14648.json`; driver `growth_family.py`.

One finding worth carrying to the other 8 regexes: **the length axis was not the obvious one.** A
plain ambiguous run with a matching tail reads SAFE on every engine, and growing this regex's
prefix is flat (76–79 ms from 66 to 281 chars). The cost lives entirely in the *trailing
whitespace* — every whitespace char is inside `` [^`"[] ``, so the star partitions a run of n of
them 2^(n-1) ways. Find the axis per regex; do not presume it.

---

## 7. The one new bug — `regex_17570` under the `v` flag

**bun spends 3.3 seconds and returns the wrong answer; node and deno answer correctly in 1.1 ms.**

Pattern (a widely-copied URL validator):

```
^(?:(?:http|https|ftp)://)(?:\S+(?::\S*)?@)?(?:(?:(?:[1-9]\d?|1\d\d|2[01]\d|22[0-3])(?:\.(?:1?\d{1,2}|2[0-4]\d|25[0-5])){2}(?:\.(?:[0-9]\d?|1\d\d|2[0-4]\d|25[0-4]))|(?:(?:[a-z¡-￿0-9]+-?)*[a-z¡-￿0-9]+)(?:\.(?:[a-z¡-￿0-9]+-?)*[a-z¡-￿0-9]+)*(?:\.(?:[a-z¡-￿]{2,})))|localhost)(?::\d{2,5})?(?:(/|\?|#)[^\s]*)?$
```

`test` on input #18, across every flag variant — the divergence is **`v`-only**:

| flags | node | deno | bun | values agree? |
|---|---:|---:|---:|---|
| none | 1.1 ms | 1.0 ms | 0.3 ms | ✅ |
| `d` | 1.2 ms | 1.1 ms | 0.3 ms | ✅ |
| `g` | 1.4 ms | 1.2 ms | 0.5 ms | ✅ |
| `i` | 2.2 ms | 1.8 ms | 0.4 ms | ✅ |
| `m` | 1.4 ms | 1.1 ms | 0.3 ms | ✅ |
| `s` | 0.9 ms | 0.9 ms | 0.3 ms | ✅ |
| **`v`** | **1.1 ms** | **1.1 ms** | **3 271.6 ms** | ❌ node/deno `true`, **bun `false`** |
| `y` | 1.4 ms | 1.1 ms | 0.6 ms | ✅ |

Six divergent cases, every one `v` or `gv`, and bun's answer is a miss in each:

| API | n | flags | node / deno | bun |
|---|---:|---|---|---|
| `test` | 18 | `v` | `true` | `false` |
| `search` | 18 | `v` | `0` | `-1` |
| `exec` | 18 | `v` | match at index 0 | `null` |
| `exec` | 57 | `v` | match at index 0 | `null` |
| `match` | 18 | `v` | match at index 0 | `null` |
| `matchAll` | 18 | `gv` | 1 match | `[]` |

On other inputs the same `v`-mode path hits the 20 s wall outright while V8 stays at 1 ms —
`replace` #56 and #57 record ratios of 14 345× and 14 872×.

**Why this is a new report and not a duplicate of the two on file:**

- Not `REPORT_bun_vmode_class_union_atomicity.md` — that bug is a lone high surrogate in the
  returned match string. Here the match is not returned at all.
- Not plain F004 (`REPORT_bun_backtracking_step_cap.md`) — in that report the pattern is genuinely
  hard and V8 also takes 2–8 s, so the cap is a mitigation misfiring on a real ReDoS. **Here V8
  takes 1.1 ms.** The pattern is not hard. Only bun's `v`-mode compilation of it explodes, and the
  same pattern under the seven other flag variants runs in 0.3 ms in bun itself.

The `v` flag is semantically near-inert for this pattern — it contains no set operations or string
literals, only ranges. V8 confirms the expectation by taking the same 1.1 ms with and without it.

### 7a. Reduction attempt, 2026-08-11 — **it is already fixed in bun 1.4.0-canary**

Reduction was attempted and stopped early, because the first rung answered the question.

Running the corpus pattern and input **verbatim** (both lifted out of
`results/regex_17570/test__18__v.js`; the recomposition is asserted byte-identical) under the
native bun at `/scratch/turcotte/verbal/engines/bun-linux-x64/bun`, version
**1.4.0-canary.1+52af83272** — 25 fresh compiles per flag:

| engine / version | flags | value | median | max |
|---|---|---|---:|---:|
| bun **1.3.14** (pinned; recorded 2026-08-05) | `v` | **`false`** ❌ | 3 271.6 ms | — |
| bun **1.4.0-canary** (2026-08-11) | `v` | **`true`** ✅ | 0.001 ms | 0.211 ms |
| bun **1.4.0-canary** (2026-08-11) | none | `true` ✅ | 0.001 ms | 0.102 ms |
| node v26.5.0 / deno 2.9.1 (recorded) | `v` | `true` ✅ | 1.1 ms | — |

**Both halves of the bug are gone in 1.4.0-canary**: the answer is correct, and the `v` penalty is
zero (0.001 ms either way, against 0.3 ms → 3 271.6 ms on 1.3.14).

The 1.3.14 result stands regardless — it is a **value**, and no amount of machine load turns `true`
into `false`. The finding was real on the pinned version; it has since been fixed upstream.

**A caution this exercise produced, worth keeping.** The first probe run measured 521 ms for the
`v` case and it nearly went into this document as a surviving 111x penalty. Repeat measurement put
the median at 0.001 ms and the max at 0.211 ms — the 521 ms was a scheduling stall on a box at
loadavg 60-80, in a freshly started process. **A single timing reading on this box is worth
nothing**, which is the same lesson §2 and §8 draw from the confirm artifact. Only the value oracle
and repeated measurement were trustworthy here.

### 7b. All four legs confirmed natively — no docker needed

The gaps above are **closed**. Docker's container-creation path stayed wedged, but `docker save`
(a read path) still worked, so the pinned engines were pulled straight out of the image layers and
run natively. Versions match `.engine-pins.json` exactly. 25 fresh compiles per flag:

| engine | version | `v` value | `v` median | no-flag value | no-flag median |
|---|---|---|---:|---|---:|
| node | v26.5.0 | `true` ✅ | 0.002 ms | `true` | 0.001 ms |
| deno | 2.9.1 | `true` ✅ | 0.002 ms | `true` | 0.001 ms |
| **bun** | **1.3.14** (pinned) | **`false`** ❌ | **3 261.7 ms** | `true` | 0 ms |
| bun | 1.4.0-canary | `true` ✅ | 0.001 ms | `true` | 0.001 ms |

**The bug reproduces exactly on the pinned bun: 25/25 `false`, median 3 261.7 ms with a tight
3 153–3 428 ms spread.** That spread matters — it is not the fat-tailed shape of a load stall (cf.
the 521 ms outlier in §7a), so the 3.3 s is real work, not contention. The recorded artifact is
fully vindicated, and the fix window is pinned to **1.3.14 → 1.4.0-canary**.

Extracting engines from the image bypasses docker entirely:
```
docker save verbal:latest -o /scratch/turcotte/verbal_img.tar     # read path; works when run/create hang
tar -xf verbal_img.tar -C img_extract
tar -xf img_extract/blobs/sha256/a0e180ee5a9b... usr/local/bin/{node,bun,deno}
```
The three binaries run directly on the host. Kept at `/scratch/turcotte/pinned_engines/usr/local/bin/`.

Remaining caveat, minor: 1.4.0-**canary** is not a release build — check a released 1.4.x before
calling the fix shipped.

---

## 8. Reconciliation with the 2026-08-03 nomination triage

That document's §4 re-ran `regex_14648` unloaded with a 300 s budget and measured bun 3 957 ms /
node 5 840 ms — **ratio 1.5**, well under the gate — and concluded "real ReDoS, not an engine
differential." The confirm pass reports ratios of 7.4–18.3 on the same regex. That looked like a
contradiction. It is not:

§4 gave node room to finish, so both sides were measured. The confirm ran at a 20 s budget, so node
is pinned at 20 000 and the ratio becomes `20000 / bun_ms`. **The Aug-3 measurement is the correct
one; the confirm's ratio on those rows is an artifact of the cap** — the same effect as §2.

The Aug-3 verdict for window 12050–15050 — *"its engine-specific yield is zero"* — **holds.** All
37 engine-specific rows on `regex_14648` are either censored (22) or genuine-but-constant-factor
(13, §6); the remaining 2 agree on no-match. Nothing in that window is a bug.

Note this does not generalise into the "queues are mostly load artifacts" rule: 12050–15050 was 54%
load artifacts (130/239), but 15050–20035 was only 19% (184/975). The nomination queue's junk rate
tracks how loaded the box was during Phase B, not anything about the window.

---

## 9. What to do next

1. **Do NOT file the `regex_17570` `v`-mode bug — it is fixed** (§7a). bun 1.4.0-canary returns the
   correct `true` in 0.001 ms on the verbatim corpus case. What remains is bookkeeping: re-run the
   node/deno and bun-1.3.14 legs once docker recovers, check a released 1.4.x rather than the
   canary, and record it in `CANDIDATES.md` as fixed-upstream so the next window does not
   re-nominate it as new.
2. ~~**Fix the ratio semantics in `_verdict` / `_confirm_redos`.**~~ **DONE 2026-08-12.** The
   classification moved to `src/redos_ratio.py`, which both call sites now import — they can no
   longer drift, which is what the "must change together" caveat here was worried about. Rows carry
   `ratio_censored`, and the flag is split into `engine_specific_measured` /
   `engine_specific_lower_bound` with `engine_specific` kept as their union so artifacts already on
   disk and `dedupe_headline.py` are unaffected. Reporting now prints the components, never the
   union alone. Censored rows *under* the gate are counted as `unresolved_censored` (§2a) rather
   than as negatives. All six existing artifacts were reclassified offline (§2b) — no re-run
   needed; sidecars are at `<artifact>.ratio_split.json`.
3. **Collapse node/deno in the reporting.** They agree within 1.2× (§3); reporting them as separate
   engines in `slowest_engine` manufactures noise. Report `V8` vs `bun`, or keep both but never
   treat a node/deno gap as signal.
4. **Do not re-run the confirm at a longer budget to rescue the 418 censored rows** until §5 is
   addressed. A longer budget yields more two-sided ratios, but the rows would still mostly be
   no-match agreements, which cannot distinguish bun's step cap from bun being correct. The
   discriminating experiment is a **length family** on the 8 backtracking regexes — the growth-curve
   fitter is already built (`redos-tracker` work), and a curve separates "different algorithmic
   class" from "constant factor" in a way no single-string ratio can.
5. ~~**`regex_14648`'s 13 clean rows (§6) are the best growth-curve input** in the set: two-sided,
   real matches, ratio 13–27×.~~ **DONE 2026-08-12 — §6a.** Same class on every engine (base ≈ 2.0),
   constant factor 12–15×, not reportable. The remaining 8 regexes are the open work, and the axis
   must be found per regex rather than presumed.

---

## Appendix — reproducing this document

```
python3 analysis/eval_help_scripts/triage_confirm_rows.py     # per-regex row/ratio/censoring breakdown (§2, §3, §4)
python3 analysis/eval_help_scripts/triage_confirm_values.py   # match vs no-match classification (§5, §6)
```

Both read only `/scratch/turcotte/verbal/results/`. No engine execution, so the numbers are
independent of how loaded the box was — which, given that §2 and §8 are both about load and
censoring artifacts, is the point.
