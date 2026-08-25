# Differential findings — cross-engine regex discrepancies

Running catalog of **confirmed cross-engine value discrepancies** surfaced by the
Verbal differential pipeline (regex → grammar → fuzz → run on node/bun/deno → diff).

Each finding has an evidence folder alongside this file containing the full
per-engine diff artifacts, the exact input strings, and the discrepant harness
reproducers, so any result here can be re-run and re-checked independently.

> Scope note: a "discrepancy" is a **value discrepancy** — the engines ran cleanly
> (no crash/timeout) and returned *different results*. Run defects (crash/timeout)
> are tracked separately and are not findings.

Engines are pinned (Docker image `verbal:latest`): **node v26.5.0, bun 1.3.14,
deno 2.9.1**. Versions are recorded in every `*.diff.json` provenance block.

---

## Index

| ID | Regex | Trigger | Engines split | # cases | Status |
|----|-------|---------|---------------|--------:|--------|
| [F001](#f001) | `[\p{L}0-9]`, `(\p{L})@`, `\p{Uppercase_Letter}` | `u` flag + a Unicode 17.0 letter | node+bun ✓ vs **deno ✗** | 88 | Confirmed (3 regexes, 2 windows) |
| [F002](#f002) | `regex_5354` (SRT parser) | `^` inside a zero-matchable group, no `m` flag | node+deno ✓ vs **bun ✗** | 40 | Confirmed (**Yarr JIT miscompile** — see [F002](#f002)) |
| [F003](#f003) | `\p{Uppercase_Letter}` | `i`+`u` flags + a letter of the opposite case | node+deno ✓ vs **bun ✗** | 52 | Confirmed (1 regex, spec-backed: **bun is wrong**) |
| [F004](#f004) | `(a+)+$` (+ `regex_3910`) | a match lying past bun's backtracking step budget | node+deno ✓ vs **bun ✗** | 7 (probe) | Confirmed (spec-backed: **bun is wrong**); **not pipeline-found** — see [why](#f004-invisible) |
| [F005](#f005) | `regex_9980`, `6663`, `8195`, `7554`, `8841`, `6071`, `9198` (+8 later) | leading `.*` under the sticky `y` flag, needing a backtrack at position 0 | node+deno ✓ vs **bun ✗** | 3677 | Confirmed (spec-backed: **bun is wrong**); all 7 witnesses verified directly |

F002 was long reserved for the `regex_5354` bun anchor candidate and is **catalogued
below as of 2026-08-03**; its investigation handoff remains at
[`HANDOFF_regex_5354.md`](HANDOFF_regex_5354.md). F003 was confirmed first and is
catalogued first; the numbering reflects the reservation, not the order of discovery.

**Three of the four findings are the same split.** F002, F003 and F004 are all
node+deno vs **bun** — i.e. **V8 vs JavaScriptCore**. F001 splits *within* V8 (node+bun
vs deno), which is why it reads as a Unicode-data version skew rather than an
algorithmic difference. A naive "2 of 3 engines agree" framing is wrong for all four,
in two different directions: for F002/F003/F004 the majority is one implementation
agreeing with itself, and for F001 the majority spans two independent engines. Where a
finding turns on the majority being *right*, it needs a fourth opinion from outside
both engines — F004 takes its ground truth from Python's `re` and from the regex's own
semantics, not from node and deno agreeing.

**F001 and F003 are independent bugs in different engines**, and they compose: see
[the three-way split](#three-way) where node, bun and deno each return a different
answer for one input.

---

## F005 — sticky `y` + a leading `.*` that must backtrack: bun returns `null` {#f005}

- **Promoted 2026-08-03** from VC-01…VC-07 in
  [`../potential_findings/CANDIDATES.md`](../potential_findings/CANDIDATES.md). Report draft:
  [`../bug_reports/REPORT_bun_sticky_dotstar.md`](../bug_reports/REPORT_bun_sticky_dotstar.md).
- **Runs:** window 6000–10050 (the 7 original witnesses, 3677 cases) and window 12050–15050
  (8 further witnesses: `regex_13813`, `14057`, `14862`, `13552`, …, 1361 sticky-flagged cases).
- **Split:** **node and deno agree, bun disagrees** — V8 vs JavaScriptCore, as with
  [F002](#f002)/[F003](#f003)/[F004](#f004).

### What differs

For a `.*`-leading pattern under the sticky (`y`) flag, on an input that has a match beginning at
position 0, bun returns `null`:

```js
new RegExp(".*x.*", "y").exec("zzx")
//  node v26.5.0 -> ["zzx"] @0    deno 2.9.1 -> ["zzx"] @0    bun 1.3.14 -> null
```

Sticky requires only that the match **begin** at `lastIndex` (= 0 here). A match provably exists —
all three engines find it with no flags. bun's sticky path returns `null` anyway, so it is unsound.

The trigger is a greedy leading `.*` that **overshoots and must backtrack**: `/.*x.*/y.exec("x")`
(no overshoot) matches everywhere, and `/.+x/y.exec("x")` is a true no-match all three agree on.

### All seven witnesses verified directly {#f005-verified}

`CANDIDATES.md` verified VC-01/02/07 and inferred the rest from shape. That gap is now closed —
a single run over all seven, each on an input whose match starts at 0:

| id | regex_id | pattern | no flags | `y` |
|----|----------|---------|:---:|:---:|
| VC-01 | `regex_9980` | `^.*@.*丁丁.*$` | @0 ✓ | **`null`** |
| VC-02 | `regex_6663` | `.*\*\/.*` | @0 ✓ | **`null`** |
| VC-03 | `regex_8195` | `.*\]\]>.*` | @0 ✓ | **`null`** |
| VC-04 | `regex_7554` | `^.*codename.*$` | @0 ✓ | **`null`** |
| VC-05 | `regex_8841` | `.*app-only.*` | @0 ✓ | **`null`** |
| VC-06 | `regex_6071` | `.*not support.*` | @0 ✓ | **`null`** |
| VC-07 | `regex_9198` | `.*Cisco Adaptive Security Appliance.*` | @0 ✓ | **`null`** |

Control `/.+x/y` on `"x"` is correctly `null` in all three engines.

### Not a JIT miscompile {#f005-not-jit}

Identical failures under `BUN_JSC_useRegExpJIT=0` (8/25 probe cases wrong either way), so this
lives in the shared/interpreter path. That distinguishes it from the two Yarr JIT miscompiles
found the same day — the `v`-mode class-union bug and the dotAll-offset bug — which both vanish
with the JIT disabled. **Despite sharing a `.*<literal>.*` pattern shape with the dotAll-offset
bug, F005 is a separate defect and must not be merged with it.**

### The `split` corollary — corrected {#f005-split}

`CANDIDATES.md` explained the non-`y` `split` discrepancies as "`split` builds a sticky matcher
internally regardless of the caller's flags". **That is not what happens.** Plain
`"zzx".split(/.*x.*/)` agrees in all three engines, as do all *numeric* limits. The real trigger
is a `limit` argument that is **not already a number**:

```js
"zzx".split(/.*x.*/, 2)    // node/deno ["",""]   bun ["",""]     ok
"zzx".split(/.*x.*/, "2")  // node/deno ["",""]   bun ["zz",""]   WRONG
```

`ToUint32("2")` is 2, so those must agree. Not string-specific: `"02"`, `" 2"`, `"2.0"`, `"2e0"`
and `{valueOf: () => 2}` all reproduce it. A plain non-regexp separator with a string limit is
correct, and so is `/.*?x/` (lazy — no backtrack at 0). Reading: bun has a fast path for
`split(regexp, numericLimit)` and a general path for a coercible limit, and only the general path
routes through the broken sticky matcher.

This matters for attribution: the ~572 no-flag `split` cases in window 12050–15050 are reached
through the harness's `"2"` string limit in its limit battery
(`[undefined,0,1,1000000,-1,2**32,2**32-1,1.5,NaN,"2"]`), **not** because split is inherently
sticky. The recorded bun value is `["zz",""]`, not "the whole string as a single element".

---

## F001 — `\p{...}` under `/u`: deno's regexp property tables are Unicode 16.0-era {#f001}

- **Runs:** three independent witnesses across two disjoint corpus windows.

  | regex_id | pattern | window | cases | evidence |
  |----------|---------|--------|------:|----------|
  | `regex_3872` | `[\p{L}0-9]` | rows 3000–3999, 2026-07-09 | 44 | [`regex_3872__pL_astral_unicode/`](regex_3872__pL_astral_unicode/) |
  | `regex_8576` | `(\p{L})@` | rows 6000–9999, 2026-07-15 | 40 | [`regex_8576_9921__unicode17_witnesses/`](regex_8576_9921__unicode17_witnesses/) |
  | `regex_9921` | `\p{Uppercase_Letter}` | rows 6000–9999, 2026-07-15 | 4 | [`regex_8576_9921__unicode17_witnesses/`](regex_8576_9921__unicode17_witnesses/) |

- **Split:** all **88** discrepancies are the **same** engine split — **node and bun
  agree, deno disagrees.** No case splits any other way, in either window.

> **Re-run note (2026-07-15, `d1f3125`).** A chaos-enabled re-run of `regex_9921`
> (see [F003](#f003)) reproduced its **4 recorded witnesses byte-identically** and
> surfaced **3 additional** F001 cases from mutated inputs, plus one input on which
> [all three engines differ](#three-way). The 88 above still describes the two
> recorded windows, which were generated without chaos and are unchanged; it is a
> floor, not a ceiling. A chaos re-run of those windows would raise it.

### What differs

Under the `u` (unicode) flag, the three engines disagree on whether certain
**code points added in Unicode 17.0 are letters**. node v26.5.0 and bun 1.3.14
classify them as letters; deno 2.9.1 does not, so it fails to match / drops the
match.

It is **a clean version cutoff**: deno answers correctly for every Unicode era up to
and including **16.0**, and misses **17.0** additions. Era ladder from a live probe
of `/\p{L}/u` on the pinned engines
(`regex_8576_9921__unicode17_witnesses/probe.js` + `probe_output.txt`, table 1):

| representative code point | Unicode era | node | bun | deno |
|---------------------------|-------------|:----:|:---:|:----:|
| U+0041 `A` | 1.0 | ✓ | ✓ | ✓ |
| U+275D9 (𧗙) CJK Ext B | 3.1 | ✓ | ✓ | ✓ |
| U+1E900 Adlam | 9.0 | ✓ | ✓ | ✓ |
| U+3038E (𰎎) CJK Ext G | 13.0 | ✓ | ✓ | ✓ |
| U+31350 CJK Ext H | 15.1 | ✓ | ✓ | ✓ |
| U+2EBF0 CJK Ext I | 15.1 | ✓ | ✓ | ✓ |
| U+105C0 Todhri | 16.0 | ✓ | ✓ | ✓ |
| U+16D40 Kirat Rai | 16.0 | ✓ | ✓ | ✓ |
| U+323B0 CJK Ext J | **17.0** | ✓ | ✓ | **✗** |
| U+16EAC Beria Erfe | **17.0** | ✓ | ✓ | **✗** |
| U+18DEF | post-16.0 | ✓ | ✓ | **✗** |

Every code point either window found deno missing falls on the 17.0 side of that
line: **U+32505, U+32777, U+32BCF, U+32C06, U+32D2C, U+32D50** (CJK Ext J,
U+323B0–U+3347F), **U+16EAC** (Beria Erfe), and **U+18DEF**. The `u`-flag dimension
is what exposes them; nothing else in the corpus reaches these tables.

(U+18DEF's block is not identified here. It is not Ext J and not Beria Erfe; all that
is established empirically is that node and bun classify it as a letter and deno does
not, which places deno's data behind node's for that code point too. Confirming which
Unicode version assigned it would tighten the cutoff claim from "16.0-era" to exact.)

> **Correction (2026-07-15).** This section previously concluded the opposite: "it is
> **not** a single clean version cutoff — it's a data-coverage gap for specific newer
> letters." That was an artifact of the original 7-code-point sample, whose only
> deno-✓ examples were CJK Ext B (3.1) and Ext G (13.0); nothing between 13.0 and
> 17.0 was ever tested. The 15.1/16.0 rungs above are the ones that were missing, and
> they pass.

**Not over-matching.** An engine answering ✓ could in principle be range-matching
whole planes rather than carrying real data. It is not: all three engines answer
`\p{L}` = false for code points unassigned in 17.0, including ones chosen to sit
immediately past the end of each block above — U+33480 (past Ext J), U+16EE0 (past
Beria Erfe), U+18E00, and unassigned planes 3/4/5 (`probe_output.txt`, table 2).

**Not only `\p{L}`.** The whole property table lags together: deno also answers
`/\p{Script=Han}/u` = false for U+323B0.

### Example (the single clearest case)

`test__11__u.js` — regex `[\p{L}0-9]`, flag `u`, input = the one character
**U+32D50** (`String.fromCodePoint(0x32D50)`, UTF-16 surrogate pair `\uD88B\uDD50`):

| engine | `/[\p{L}0-9]/u.test(String.fromCodePoint(0x32D50))` |
|--------|:---:|
| node   | `true`  |
| bun    | `true`  |
| deno   | **`false`** |

The same input under `exec` returns a match object on node/bun and `null` on deno;
under `matchAll` (multi-match strings) deno omits the astral matches that node/bun
return. Same root cause across all 5 APIs.

### Root cause

A **bundled-Unicode-data version skew**, not a JS-engine-version difference: the
regexp property tables each runtime ships are at different Unicode versions —
node and bun at 17.0, deno at 16.0.

Notably, **deno's V8 is *newer* than node's** (V8 14.9.207 vs 14.6.202) — so this is
specifically about the *data*, independent of the underlying JS engine version.
(bun, on JavaScriptCore, agrees with node.)

**The runtimes' self-reported versions do not explain the split and must not be used
as evidence for it.** Both of them mislead, in opposite directions
(`probe_output.txt`, header + table 3):

| runtime | self-reports | ICU case data (`toLowerCase`) | regexp tables (`\p{Lu}`) |
|---------|--------------|-------------------------------|--------------------------|
| node | `unicode=17.0 icu=78.3` | 17.0 (U+16EAC → U+16EC7) | 17.0 ✓ |
| bun | `unicode=15.1 icu=75.1` | **pre-17.0** (no mapping) | **17.0 ✓** |
| deno | `unicode=17.0 icu=78.3` | pre-17.0 (no mapping) | **16.0 ✗** |

- **deno claims Unicode 17.0 / ICU 78.3 — the same numbers node reports — while its
  regexp tables behave as 16.0.** So the earlier framing ("node reports 17.0; deno's
  bundled data is older") had the conclusion right but the evidence wrong: deno does
  not report older data, it reports 17.0 and does not deliver it. That inconsistency
  is the sharpest thing to put in an upstream report.
- **bun reports 15.1 yet its regexp tables are 17.0**, so `process.versions.unicode`
  does not describe the regexp property tables at all.

**bun has its own internal skew** (new, not part of the original finding): its regexp
tables are 17.0 while its ICU case-mapping data is pre-17.0 — `"\u{16EAC}".toLowerCase()`
is a no-op on bun but maps to U+16EC7 on node. JSC's Yarr tables and bun's bundled
ICU are versioned independently. So **"node and bun agree" is superficial** — they
agree on the regexp tables while disagreeing about the same character elsewhere. This
particular skew is still unreachable for the pipeline, which exercises only the five
regex APIs and never case mapping ([G5](../EXPERIMENT_GAPS.md#g5)).

> **Update (2026-07-15, `d1f3125`).** "node and bun agree" is now known to be false in
> a way a regex API *can* see: under `/i`, bun does not case-fold property escapes at
> all — [F003](#f003). F001's split (node+bun vs deno) is exactly right **for F001's
> cases**, all of which turn on the property tables; it is not a general statement
> that node and bun implement `\p{...}` alike. The two engines are wrong about
> different characters for different reasons, and one input makes
> [all three disagree at once](#three-way).

This is a genuine, reproducible cross-engine semantic difference in `\p{...}`
handling — exactly the class of divergence the flag-variation `u` dimension was
added to surface.

### Hit rate: 2 of the 3 property-escape regexes that actually ran

The 6000–9999 window contains **13** regexes using `\p{...}`/`\P{...}`, and only 2
flagged — but that ratio is misleading. **Ten of the 13 never executed a single
case**, for two reasons that the run record does not surface:

| | count | why |
|---|--:|---|
| harness never compiles, on any engine | **7** | `SyntaxError`. Perl/POSIX property names JS does not have (`\p{Space}`, `\p{IsAlpha}`, `\p{XDigit}`, `\p{Alpha}`, `\p{Alnum}`, `\p{Print}`) or escapes illegal under `/u` (`[\,…]`, `[\Â…]`). All are valid JS *without* `/u`, which is how they passed the `not_js` gate; the specializer then requires `/u` because it sees `\p{`, and the harness throws. Recorded as `status: ok`. |
| generated zero strings | **3** | `regex_6784`, `regex_8033`, `regex_8084` — huge classes with unbounded repetition; the fuzzer produced nothing within `fuzz_timeout_s`. Recorded as `status: ok` with `num_strings: 0` for all 5 APIs. |
| **actually executed** | **3** | `regex_6872`, `regex_8576`, `regex_9921` |

Of the 3 that ran, **2 flagged**. The third, `regex_6872` (`\p{Script=Cypriot}+`),
*cannot* — Cypriot (U+10800–U+1083F) was assigned in Unicode 4.0, so no input drawn
from it ever reaches the 17.0 data that splits the engines.

So among property-escape regexes that both execute and can sample a 17.0 code point,
the hit rate in this window is **2/2**. F001 is not a lucky find; it is close to
universal in the population that reaches it. The under-reporting is upstream of
detection — 10 of 13 candidate regexes were silently dropped before a single engine
ran, and the headline (`regexes_evaluated: 3767`) counts all 10 as evaluated.

`regex_9780` is the sharpest illustration: its inputs contain **48** code points from
13 distinct 17.0-era characters (U+3250A, U+32777, U+32D50, …), every one of which
node classifies as a letter and deno does not. It contributed zero cases, because
`[\,.:;!?]` is a `SyntaxError` under `/u`.

Both failure modes are ~0.2% of the window each, but land almost entirely on
`\p{...}` regexes (7/13 and 3/13). The non-compiling one is total: **every** regex in
the window that fails to compile on every engine is a `\p{...}` regex. Both are
analysed in [`../EXPERIMENT_GAPS.md`](../EXPERIMENT_GAPS.md) (G1, G2).

### The 88 discrepant reproducers

One harness file per (api, string, flag set). **Every** flag combination that triggers
the split, in all three regexes, **contains `u`** — the property lookup only consults
the Unicode tables in unicode mode.

`regex_3872__pL_astral_unicode/harnesses/` — **44 files**:

- **`test` / `exec` / `replace` / `split`** — strings `n=11` (U+32D50) and `n=17`
  (U+32777), each under flags `u`, `iu`, `mu`, `su` → 4 APIs × 2 strings × 4 flags
  = **32 files**.
- **`matchAll`** — strings `n=3`, `n=4`, `n=5` (each a multi-line string mixing
  astral CJK that deno misses with a code point it matches), under flags `gu`,
  `giu`, `gmu`, `gsu` (`g` mandatory) → 3 × 4 = **12 files**.

`regex_8576_9921__unicode17_witnesses/regex_8576/harnesses/` — **40 files**:

- **`test` / `exec` / `replace` / `split`** — strings `n=14` (U+32C06) and `n=15`
  (U+32D2C / U+32505), each under `u`, `iu`, `mu`, `su` → **32 files**.
- **`matchAll`** — strings `n=5` and `n=14`, under `gu`, `giu`, `gmu`, `gsu`
  → **8 files**.

`regex_8576_9921__unicode17_witnesses/regex_9921/harnesses/` — **4 files**:

- **`matchAll`** — string `n=15` (mixes U+16EAC, which deno misses, with BMP
  uppercase letters it matches), under `gu`, `giu`, `gmu`, `gsu`. deno returns the
  two BMP matches and silently drops the astral one.


### Reproduce

```bash
# any single reproducer, on the pinned engines. verbal:8dc8b1d produced the
# 6000-9999 artifacts; the engines are identical across image tags.
cd ~/projects/verbal
F=analysis/differential_findings

for e in "node" "bun" "deno run --quiet"; do echo "== $e =="; docker run --rm \
  -v "$PWD/$F/regex_3872__pL_astral_unicode:/f:ro" --entrypoint sh verbal:8dc8b1d \
  -c "$e /f/harnesses/test__11__u.js"; done
# node/bun print value:true ; deno prints value:false

for e in "node" "bun" "deno run --quiet"; do echo "== $e =="; docker run --rm \
  -v "$PWD/$F/regex_8576_9921__unicode17_witnesses:/f:ro" --entrypoint sh verbal:8dc8b1d \
  -c "$e /f/regex_8576/harnesses/test__14__u.js"; done
# node/bun print value:true ; deno prints value:false

# the root-cause probe (era ladder + unassigned controls + case-mapping skew)
for e in "node" "bun" "deno run --quiet"; do docker run --rm \
  -v "$PWD/$F/regex_8576_9921__unicode17_witnesses:/f:ro" --entrypoint sh verbal:8dc8b1d \
  -c "$e /f/probe.js"; done
# reproduces probe_output.txt verbatim
```

---

## F002 — `^` inside a zero-matchable group anchors bun's whole pattern {#f002}

- **Run:** rows 4000–5999, corpus_sha `999fe71e…`, config `config/fullcorpus.yaml`
  (config_sha `d769e16a…`), seed 0, git_commit `48defb5`. Results dir:
  `results-run-4000-5999/`. Evidence:
  [`regex_5354__bun_anchor_hoist/`](regex_5354__bun_anchor_hoist/) — `probe.js` +
  `probe_output.txt`, `matchAll.diff.json` (all 80 cases), the exact reproducer
  harness `matchAll__0__g.js`, and the `.fan` / `.strings.jsonl` inputs.
- **Regex:** `regex_5354`, an SRT subtitle-block parser —
  `(.+)\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\n((?:^.*$\n)*?)\n`.
  The `^` lives in `((?:^.*$\n)*?)`, a **lazy** group that readily matches zero times.
- **Split:** **node and deno agree, bun disagrees** — V8 vs JavaScriptCore, the same
  split as [F003](#f003) and [F004](#f004).
- **40 discrepant cases, all `matchAll`.** The flag split is total: `g` 20/20 and
  `gi` 20/20 diverge; `gm` 0/20 and `gs` 0/20 do not. **`m` makes it vanish — that is
  the tell.**
- **Reproducibility:** all 411 artifacts regenerate byte-for-byte once given their
  chunk context ([G6](../EXPERIMENT_GAPS.md#g6-resolved)).

### What differs

Minimal reproducer — nine characters:

```js
Array.from("ay".matchAll(/(?:^x)*?y/g))
// node v26.5.0 -> [ "y" @ 1 ]   deno 2.9.1 -> [ "y" @ 1 ]   bun 1.3.14 -> [ ]
```

The group matches zero times, so `^` need never be satisfied and `y` at index 1 must
match. bun returns nothing.

**Root cause (probe-confirmed):** JSC treats a `^` occurring inside a zero-matchable
group as if it anchored the whole pattern, and so refuses any match at index > 0 while
`m` is absent. The controls rule out the obvious alternatives — bun handles a genuine
`^` anchor correctly (`/^y/g` on `"ay"` is correctly no-match in all three engines) and
is correct once `m` is set. It reproduces with `*?`, `*` and `?`, so laziness is not
the trigger, and with a bare `(?:^)*?`, so no inner literal is needed either.

### Re-verified 2026-08-03, with three additions {#f002-2026-08-03}

Re-run against the pinned image; **still fails, 9 of 18 probe cases**. Three facts the
original 2026-07-14 investigation did not have:

1. **It is a Yarr JIT miscompile.** Under `BUN_JSC_useRegExpJIT=0` every case is
   correct — 9/18 wrong with the JIT, **0/18 without**. This makes F002 the third
   JIT-only bun finding, alongside the `v`-mode class-union bug and the dotAll
   offset bug (see [`../bug_reports/README.md`](../bug_reports/README.md)); the
   sticky-`.*` bug and the `lastIndex`-surrogate bug both survive that flag.
   It also settles ground truth without a cross-engine vote: the same binary
   disagrees with itself across execution tiers.
2. **The symmetric `$` bug does not exist.** The handoff listed it as the obvious
   unrun test. It is now run: `/y(?:x$)*?/g`, `/y(?:x$)*/g`, `/y(?:x$)?/g` and
   `/y(?:$)*?/g` on `"ya"` all correctly match `"y"` at 0 in **all three engines**.
   The defect is specific to `^`, not to anchors in zero-matchable groups generally.
3. **It is not global-specific.** `/(?:^x)*?y/` with no flags at all fails in bun too;
   the original probe only exercised `g`.

### The pipeline under-reports this {#f002-underreport}

Only `matchAll` flagged it — `exec`, `test`, `replace` and `split` each ran 0/80. That
is **not** an API semantic difference but an artifact of input shape: the `matchAll`
specialization emits `<start> ::= <pad> (<m> <pad>){2,K}`, so its strings begin with a
pad and the match lands at index 50, whereas the other specializations put the match at
index 0 — where `^` is satisfied and bun agrees. The bug needs a match at index > 0 to
appear at all.

So the real blast radius is wider than the case count suggests, and the fix is a
pipeline question rather than a `regex_5354` one: if the non-`matchAll` specializations
also explored a leading pad, this class of bug would surface across the whole corpus.

---

## F003 — `\p{...}` under `/iu`: bun does not case-fold property escapes {#f003}

- **Run:** rows 9921–9922, 2026-07-15, provenance `d1f3125`, image `verbal:d1f3125`.
  Evidence: [`regex_9921__bun_ignorecase_property_escape/`](regex_9921__bun_ignorecase_property_escape/)
  — the `.fan`/`.strings.jsonl`/`.diff.json` for all 5 APIs, the headline and run
  record, and `harnesses/` with **all 59** discrepant cases from the run. 52 of those
  are F003 and 8 are F001, overlapping in the one case where
  [both fire](#three-way); see [the split table](#f003-splits). The F001 cases are
  kept here because they came out of the same run and the same artifacts.
- **Regex:** `regex_9921` = `\p{Uppercase_Letter}` (the same corpus row that
  contributes 4 cases to [F001](#f001) — the two findings are unrelated bugs that
  this one regex happens to reach).
- **Split:** **node and deno agree, bun disagrees** — the mirror image of F001's
  split, and one reason the two are clearly distinct.
- **52 discrepant cases**, every one of which carries **both `i` and `u`**.

### What differs

Under `i` + `u`, bun does not apply case folding to a `\p{...}` property escape.
The single clearest case (`test__24__iu.js`):

| engine | `/\p{Uppercase_Letter}/iu.test("ც")` |
|--------|:---:|
| node   | `true`  |
| deno   | `true`  |
| bun    | **`false`** |

(`ც` is U+10EA GEORGIAN LETTER CAN; its Mtavruli capital `Ც` U+1CAA is
`General_Category=Lu` and therefore in `\p{Uppercase_Letter}`, so under `/i` the set
must match it. `chaos` reached it with `case_flip@0` on a generated `Ც`.)

### bun is wrong — this is not a defensible reading

Unlike F001, which is a data-version skew where no engine is misreading the spec,
F003 is a **conformance bug with a specific correct answer**. Per ES2024
§22.2.2.7.1 (`CharacterSetMatcher`), under `/iu` the input is canonicalized to `cc`
and the set matches if *there exists* a member `a` of the set with
`Canonicalize(a) === cc`. `scf("ც")` is `"ც"`; `"Ც"` is in `\p{Uppercase_Letter}`;
`scf("Ც")` is `"ც"`. So it must match, and node and deno both do.

**bun contradicts itself**, which is what convicts it. From the spec-derived probe
([`probe_ignorecase.js`](regex_9921__bun_ignorecase_property_escape/probe_ignorecase.js)
+ [`probe_ignorecase_output.txt`](regex_9921__bun_ignorecase_property_escape/probe_ignorecase_output.txt),
run on the pinned engines) — **bun scores 5/11 where node and deno each score 11/11**:

| probe | expected | node | deno | bun |
|-------|:--------:|:----:|:----:|:---:|
| `/\p{Lu}/iu.test("a")` | `true` | ✓ | ✓ | **✗** |
| `/\p{Ll}/iu.test("A")` (mirror) | `true` | ✓ | ✓ | **✗** |
| `/\p{Lu}/iu.test("é")` (non-ASCII BMP) | `true` | ✓ | ✓ | **✗** |
| `/\p{Uppercase_Letter}/iu.test("a")` (long name) | `true` | ✓ | ✓ | **✗** |
| `/[\p{Lu}]/iu.test("a")` (inside a class) | `true` | ✓ | ✓ | **✗** |
| `/\p{Lu}/vi.test("a")` (`v` instead of `u`) | `true` | ✓ | ✓ | **✗** |
| `/\p{Lu}/iu.test("A")` | `true` | ✓ | ✓ | ✓ |
| `/\p{Lu}/u.test("a")` — CONTROL, no `i` | `false` | ✓ | ✓ | ✓ |
| `/\p{Ll}/u.test("A")` — CONTROL, no `i` | `false` | ✓ | ✓ | ✓ |
| **`/[A-Z]/iu.test("a")` — CONTROL, range folding** | `true` | ✓ | ✓ | **✓** |
| **`/[a-z]/iu.test("A")` — CONTROL, range folding** | `true` | ✓ | ✓ | **✓** |

The last two rows are the argument. **bun folds literal ranges correctly and
property escapes not at all** — so it is not applying a different-but-coherent
theory of `/i`; it applies folding in one place and omits it in the other. The `/u`
controls also pass, so the property set itself is right; only the folding step is
missing. Reproduces under both `u` and `v`, inside and outside character classes,
on ASCII and non-ASCII.

Root cause is not established from outside, but the shape is consistent with JSC's
Yarr building property-escape sets without running them through the same
canonicalization path it applies to ranges.

### The three-way split — F001 and F003 compose {#three-way}

One input makes **all three engines return different answers**
(`matchAll__50__giu.js`, regex `\p{Uppercase_Letter}`, flags `giu`, input
`"a\u{16EAC}\nᲺ\nР\n"`):

| engine | matches returned | why |
|--------|------------------|-----|
| node | `a`, U+16EAC, `Ჺ`, `Р` (4) | correct on both axes |
| bun | U+16EAC, `Ჺ`, `Р` (3) | drops `a` — **F003**, no folding for `\p{...}` |
| deno | `a`, `Ჺ`, `Р` (3) | drops U+16EAC — **F001**, 16.0-era tables |

Neither finding alone predicts this: it needs bun's folding bug *and* deno's table
lag in the same string. It is also the sharpest demonstration that the two are
independent — each engine is wrong about a different character, for a different
reason, in one `matchAll` call.

### How it was found — and why it was invisible before

F003 was surfaced **by the pipeline**, on the first run after
[`chaos`](../EXPERIMENT_GAPS.md#g7) landed. It had been invisible for a reason
worth recording, because it was a flaw in the experiment rather than bad luck:
`regex_9921`'s flag variants **already included `giu`** — the exact regex, the exact
flag — but Stage 3 samples a grammar *of the regex's language*, so all 20 generated
strings were uppercase. Exposing the bug needs a **lowercase** letter: a string
`\p{Uppercase_Letter}` by construction never generates. See
[G3b](../EXPERIMENT_GAPS.md#g3).

`chaos` perturbs each generated string, and the op that cracked this one is named
for the gap: `case_flip`. The full provenance of the clearest case is four fields in
`test.strings.jsonl`, and it is the whole argument of
[G7](../EXPERIMENT_GAPS.md#g7) in one row:

```
n=2   origin=fuzz   py_re_matches=1   "Ც"    <- what the grammar can generate: a match
n=24  origin=chaos  py_re_matches=0   "ც"    <- case_flip@0 of n=2: outside the language
      seed_n=2  mutation=case_flip@0         <- and this is where bun disagrees
```

The fuzzer can only ever produce the first row. The bug is only visible on the
second. Every mutant records `seed_n` + `mutation`, so it is reconstructible from its
seed string by hand.

The same regex, same engines, same flags, chaos the only variable:

| | cases | value discrepancies |
|---|------:|--------------------:|
| chaos off (the pipeline before `d1f3125`) | 400 | 4 (all F001) |
| chaos on (`chaos_n: 2`) | 1,200 | **59** |

#### What the 59 cases actually are {#f003-splits}

They decompose by **engine split**, which is what identifies the finding — not by
which population the string came from:

| split | cases | finding | origins |
|-------|------:|---------|---------|
| node+deno vs **bun** | 51 | **F003** only | all chaos |
| node+bun vs **deno** | 7 | F001 only | 4 fuzz + 3 chaos |
| all three differ | 1 | **both at once** | chaos |
| | **59** | | **4 fuzz + 55 chaos** |

So F003 = 51 + 1 = **52** and F001 = 7 + 1 = **8** in this run; the three-way case is
counted in both, because both bugs fire in it. The index table's 88 for F001 is
untouched by this — it describes the two recorded windows, which predate chaos.

The 4 fuzz cases are byte-identical to F001's recorded `regex_9921` witnesses,
which is the control: chaos appended without disturbing the fuzz population or its
`n` ids. Chaos also added 3 *new* F001 cases — it is not specific to F003.

The 52 F003 cases break down as:

| by chaos op | | by API | | by flags | |
|---|--:|---|--:|---|--:|
| `case_flip` | 26 | `matchAll` | 13 | `iu` | 39 |
| `insert` | 14 | `replace` | 12 | `giu` | 13 |
| `substitute` | 12 | `exec` | 10 | | |
| | | `split` | 10 | | |
| | | `test` | 7 | | |

Three points worth drawing out:

- **All five APIs see it** — unlike the F002 candidate, which only `matchAll` could
  reach. F003 is not an artifact of one API's harness.
- **Every case carries `i`**, and no case carries `i` *without* `u`. That is the
  finding's signature: `\p{...}` requires `u`, and the bug is in the `i` step.
- `insert` and `substitute` contribute because `chaos_alphabet` contains the
  lowercase `a` and `é` — a reminder that the alphabet is a real experimental
  parameter, not filler. `case_flip` is the op that targets this class directly, and
  it found half of them.

By contrast, all **7** F001 cases in this run are `matchAll` — F001 needs an astral
17.0 letter in the input, and in this regex only `matchAll`'s multi-match strings
carry one.

> **Scope of the claim.** F003 is confirmed on one regex. The probe shows the bug is
> general to `\p{...}` under `/i` (it reproduces on `\p{Lu}`, `\p{Ll}`,
> `\p{Uppercase_Letter}`, inside classes, under `v`), so the single-regex evidence is
> a limit of *where we have run chaos so far*, not of the bug. A chaos re-run of the
> 6000–9999 window would establish the real blast radius; that has not been done.

### Reproduce

```bash
cd ~/projects/verbal
F=analysis/differential_findings/regex_9921__bun_ignorecase_property_escape

# the single clearest reproducer: /\p{Uppercase_Letter}/iu.test("ც")
for e in "node" "bun" "deno run --quiet"; do echo "== $e =="; docker run --rm \
  -v "$PWD/$F:/f:ro" --entrypoint sh verbal:d1f3125 \
  -c "$e /f/regex_9921/harnesses/test__24__iu.js"; done
# node/deno print value:true ; bun prints value:false

# the three-way split: node, bun and deno each return something different
for e in "node" "bun" "deno run --quiet"; do echo "== $e =="; docker run --rm \
  -v "$PWD/$F:/f:ro" --entrypoint sh verbal:d1f3125 \
  -c "$e /f/regex_9921/harnesses/matchAll__50__giu.js"; done
# node: 4 matches ; bun: 3 (drops "a") ; deno: 3 (drops U+16EAC)

# the spec-conformance probe (bun 5/11, node and deno 11/11)
for e in "node" "bun" "deno run --quiet"; do docker run --rm \
  -v "$PWD/$F:/f:ro" --entrypoint sh verbal:d1f3125 \
  -c "$e /f/probe_ignorecase.js"; done
# reproduces probe_ignorecase_output.txt verbatim

# regenerate the whole evidence run from provenance (~2 min)
docker run --rm --entrypoint sh verbal:d1f3125 \
  -c "cd /app && python eval/run_eval.py --config config/fullcorpus.yaml \
      --start 9921 --limit 1 --workers 8"
# cases run: 1200 ; VALUE DISCREPANCIES: 59 ; run defects: 0
```

---

## F004 — bun abandons backtracking at a step budget and reports "no match" {#f004}

- **Found:** 2026-07-17, image `verbal:d1f3125`, while validating the timing-vs-length
  method for [the ReDoS length axis](../HANDOFF_redos_timing.md). Evidence:
  [`bun_backtrack_cap__unsound_step_limit/`](bun_backtrack_cap__unsound_step_limit/)
  — the three probes and their verbatim output.
- **Regex:** `/(a+)+$/` (synthetic). The same cap is reached by `regex_3910`, a real
  corpus row — see [the step-budget evidence](#f004-steps).
- **Input family:** `"a"*n + "!aaa"`.
- **Split:** **node and deno agree, bun disagrees** — the same V8-vs-JavaScriptCore
  split as [F002](#f002)/[F003](#f003).
- **Not found by the pipeline.** Every other finding here was surfaced by a pipeline
  run; this one was not, and could not be. See [why](#f004-invisible).

### What differs

`/(a+)+$/` is not anchored at the start, so it matches the trailing `aaa`: **the
correct answer is `true` for every n.** But a backtracking engine reaches that match
only after failing at start positions `0..n-1`, each of which costs a full exponential
partition search of the leading `a`-run. The match sits on the far side of the
exponential wall.

At **n=26** bun stops searching and reports no match
([`bun_cap_probe_output.txt`](bun_backtrack_cap__unsound_step_limit/bun_cap_probe_output.txt)):

| n | node | deno | bun |
|--:|------|------|-----|
| 24 | `true` (2183ms) | `true` (1744ms) | `true` (227ms) |
| 25 | `true` (4393ms) | — | `true` (453ms) |
| **26** | **`true`** (8813ms) | **`true`** (6977ms) | **`false`** (679ms) |
| 28…100 | timeout >25s | timeout >25s | **`false`** (~678ms, flat) |

It stays `false` out to n=100 and beyond: past the budget the answer no longer depends
on the input at all.

**Ground truth is not "node and deno agree"** — they are both V8, so that is one
implementation agreeing with itself. It is (a) the regex's own semantics, since an
unanchored search reaches the trailing `aaa` from start position n+1 whatever precedes
it, and (b) Python's `re`, an independent implementation, which matches `'aaa'` at
every n small enough to finish.

### bun is wrong — and throwing would have been defensible

ECMA-262 defines regex matching as a total function: `RegExpBuiltinExec` runs the
Matcher and returns a match iff one exists (§22.2.7.2). There is no resource-limit
escape hatch in the matching semantics, and `test` is specified as `exec !== null`.

The conformance argument does not rest on that alone, because implementations are
generally permitted to fail on resource exhaustion. That is exactly the point: **a
`RangeError` would be defensible; a `false` is not.** bun does not signal exhaustion —
it returns a value that is *indistinguishable from a genuine no-match*, so no caller
can tell the difference. Compare [F003](#f003), where the argument is that bun
contradicts itself; here it is that bun answers a question it did not finish.

bun also has the right answer within reach: at n=25 it returns `true` in 453ms. At
n=26 it gives up at 679ms. The step budget is the only thing that changed.

**The security reading is the wrong way round.** A backtracking cap exists to *prevent*
ReDoS. On a regex used to *detect* something — a validator, a filter, a sanitiser — this
cap converts a denial-of-service into a **silent bypass**: make the input long enough
and the match disappears. The hardening measure introduces the soundness bug.

### The budget is in steps, not milliseconds {#f004-steps}

This is what makes the finding reproducible rather than host-lore
([`cap_kind_output.txt`](bun_backtrack_cap__unsound_step_limit/cap_kind_output.txt)):

| regex | bun's plateau |
|-------|--------------:|
| `/(a+)+$/` | ~678ms |
| `regex_3910` (`(?:\b[a-z\d](?:[_.:+]?[a-z\d]+)*_?_\|…)`) | ~1780ms |

Two different plateaus, so the budget is **not a clock** — it is a step count, and the
heavier inner loop simply takes longer to spend it. Consequences:

- **The crossover n and the wrong value are host-independent** and reproduce from
  provenance. A time-based cap would have moved the crossover with host speed (a faster
  machine getting further before the clock ran out), making the finding unreproducible
  in the way [G6](../EXPERIMENT_GAPS.md#g6) is about.
- **The plateau's wall-clock is host-specific** and carries no meaning beyond this
  machine. Cite the crossover, not the milliseconds.

### Why the timing tracker cannot see this {#f004-invisible}

[`HANDOFF_redos_timing.md`](../HANDOFF_redos_timing.md) built a ReDoS tracker whose
"load-bearing half" is the timeout trigger. **That trigger can never fire for bun on
this class of regex**, because bun does not time out — it caps. The tracker is blind to
JSC's most interesting behaviour by construction.

The same measurements correct that document's central claim. Over n=17..25 bun is
exponential at **base 2.00 (R²=1.0000)** — statistically identical to node (1.991) and
deno (2.001) — and only then goes flat
([`sweep_probe_output.txt`](bun_backtrack_cap__unsound_step_limit/sweep_probe_output.txt)):

```
bun: (17,1.81ms) (19,7.17ms) (21,28.62ms) (23,111.91ms) (25,460.29ms)  <- base 2.00
     (27,673ms) (29,682) (31,669) (33,682) (35,684) (37,678) (40,682)  <- FLAT
```

So bun does **not** "not blow up". It blows up exactly as fast as V8 and then refuses to
finish. The handoff's `686ms` — treated there as evidence bun handles the regex well,
and its exact reproducibility as evidence the measurement was honest — **is the plateau**
(`cap_kind_output.txt` reads 686.1ms at n=26). It reproduces to the millisecond because
it is a budget being spent, not work being measured. Same number, opposite meaning. The
recorded `29.4x` "engine-specific" ratio is therefore V8-unbounded against JSC-capped, a
constant factor between two base-2 engines, not an algorithmic difference.

**Why no pipeline run has found it.** The input needs a `!` inserted into an `a`-run
long enough to exhaust the budget (~26 chars). `chaos`'s existing `insert` op produces
exactly that shape — this is not a missing feature — but Stage 3 generates
in-language strings that are far too short to reach the budget, so the mutant never
lands past the cap. The missing ingredient is **input length**, which is
[the open next step](../HANDOFF_redos_timing.md) for the ReDoS work. F004 is the
evidence that the length axis pays for itself in *value discrepancies*, not only in
ReDoS proofs.

### Reproduce

```bash
# the finding: bun returns false where node and deno return true (~4 min; node
# and deno genuinely take ~9s and ~7s at n=26, and time out past it)
docker run --rm -v "$PWD":/repo verbal:d1f3125 \
  python3 /repo/analysis/differential_findings/bun_backtrack_cap__unsound_step_limit/bun_cap_probe.py
# reproduces bun_cap_probe_output.txt: bun flips to false at exactly n=26

# steps-not-milliseconds: two regexes, two plateaus (~2 min)
docker run --rm -v "$PWD":/repo verbal:d1f3125 \
  python3 /repo/analysis/differential_findings/bun_backtrack_cap__unsound_step_limit/cap_kind.py
# reproduces cap_kind_output.txt: ~678ms vs ~1780ms

# the curves behind the retraction: bun base 2.00 to n=25, then flat (~5 min)
docker run --rm -v "$PWD":/repo verbal:d1f3125 \
  python3 /repo/analysis/differential_findings/bun_backtrack_cap__unsound_step_limit/sweep_probe.py 2
# reproduces sweep_probe_output.txt

# the one-liner, if you only want to see it
docker run --rm verbal:d1f3125 bash -c \
  'for e in node bun; do echo -n "$e: "; $e -e "console.log(/(a+)+\$/.test(\"a\".repeat(26)+\"!aaa\"))"; done'
# node: true ; bun: false
```
