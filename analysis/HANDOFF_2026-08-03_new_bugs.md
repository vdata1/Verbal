# Handoff — investigate the new bugs from window 12050–15050

**Written:** 2026-08-03 · **Source window:** `results/eval_headline_12050_15050.json`
(`complete: true`, `git_commit=7f128c39...` clean, node v26.5.0 / bun 1.3.14 / deno 2.9.1)
· **Predecessor handoffs:** `HANDOFF_2026-07-21.md`, `HANDOFF_redos_timing.md`

> **STILL LIVE — re-verified 2026-08-12.** This is the most open work in the repo: items
> A–D and F are all *drafted but unfiled*, and `bug_reports/FILING_PLAN.md` still opens
> with "Nothing has been filed." Item **E is DONE** (`eval/confirm_redos.py` was built,
> applied, and its output triaged on 2026-08-11 — see
> `redos_nomination/TRIAGE_CONFIRM_2026-08-07.md`).

> **Read this first:** the headline's two largest families are **already-known, already-drafted
> bugs**. Only two things in this window are new, and both are reduced to one-line repros below.
> Do not re-triage the sticky-`.*` clusters.

---

## 0. TL;DR — what to actually work on

| # | Item | State | Effort |
|---|------|-------|--------|
| **A** | bun `v`-mode class union loses code-point atomicity | **report DRAFTED 2026-08-03**; localized to the Yarr JIT | file (venue: WebKit?) |
| **B** | bun unicode-mode `lastIndex` inside a surrogate pair | **report DRAFTED 2026-08-03**; spec does NOT settle it — see §3 correction | decide venue (tc39#128?) |
| C | sticky-`.*` family (1361+ cases) | **KNOWN**, report drafted 2026-07-24, **unfiled** | finish 2 checklist boxes, file |
| D | F001 deno `\p{...}` tables (586 cases) | **KNOWN**, report drafted, unfiled | file |
| E | 239 ReDoS nominations | **DONE 2026-08-03** — triaged (0 engine-specific findings) and confirm consumer built + tested | apply `eval/confirm_redos.py`, then run it |
| F | ~170 `matchAll` cases in the no-`u`/`v`/`y` bucket | **RESOLVED 2026-08-03 — a NEW third bug**, report drafted | file (venue: WebKit?) |

---

## 1. How the window's 3772 discrepancies partition

42 distinct regexes → 46 root-cause clusters (82× amplification). By flag family:

| Bucket | Cases | Regexes | Dominant APIs | Cause |
|---|---:|---:|---|---|
| unicode (`u`/`v`, no `y`) | 1669 | 42 | split 551, matchAll 411, exec 231 | mix of **A**, **B**, and F001 |
| sticky (`y`) | 1361 | 8 | test/exec/match ~230 each | **C** (known) |
| no `u`/`v`/`y` | 742 | 3 | split 572, matchAll 170 | **C**'s split corollary + **F** |

`dedupe_headline.py` reports "known-cause share: 16%". **That number only counts F001** — it has
no tag for the sticky bug. The true known share is roughly **16% + 36% ≈ half the window**.

**Two known traps in `dedupe_headline.py`:**
1. It does **not** merge the sticky-`.*` family. It keys clusters on the exact flag-string set,
   which differs per regex, so one bug appears as 6+ separate "NEW" clusters at the top of the
   report, sorted by size — i.e. the most eye-catching output is the least novel. Filter
   discrepancies on `'y' in flags` to collapse it.
2. Its "34 regexes share a signature" line for `matchAll`+`gv` is **amplification, not breadth** —
   see B below.

---

## 2. Bug A — bun `v`-mode class union loses code-point atomicity  ⭐ NEW

**Minimal repro** (verified 2026-08-03 under all three engines):

```js
new RegExp("[\\s\\t\\p{C}]", "v").exec("\u{E8541}")
```

| Engine | Result |
|---|---|
| node v26.5.0 | `"\u{E8541}"` — length **2**, the whole code point ✅ |
| deno 2.9.1 | `"\u{E8541}"` — length **2** ✅ |
| **bun 1.3.14** | `"\uDB61"` — length **1**, a **lone high surrogate** ❌ |

**Why this matters:** bun hands back a string that is not a valid code point. Any caller that
slices, re-encodes, or concatenates the match gets mojibake or an unpaired surrogate.

**Isolation — the trigger is the class union, not the property:**

```js
"[\\p{C}]"        /v  -> all engines length 2   ✅ correct
"[\\s\\p{C}]"     /v  -> all engines length 2   ✅ correct
"[\\t\\p{C}]"     /v  -> all engines length 2   ✅ correct
"[\\s\\t\\p{C}]"  /v  -> bun length 1           ❌ BUG
"[\\s\\t\\p{C}]"  /u  -> all engines length 2   ✅ correct — v-mode only
```

Note `\t` ⊂ `\s`. The trigger needs **three operands with an overlapping pair**, and only under
`v` (unicodeSets). Working hypothesis: bun's v-mode set-union/dedup step mis-merges overlapping
operands and emits a matcher that has lost its code-point (as opposed to code-unit) stride.

> **CORRECTION 2026-08-03 (later the same day) — both sentences above are wrong.** Overlap is
> not required (`[ab\p{C}]` fails with disjoint operands) and operand **order** matters
> (`[\t\s\p{C}]` is correct while `[\s\t\p{C}]` — same operand set — is wrong). Nor is it a
> "lost stride": with `[\s\t\p{L}]` bun returns `\uD801`, a code unit the class does **not**
> contain, so it is not a code-unit view of the same set. It is also spelling-sensitive —
> `[ab\p{C}]` fails but `[\u0061\u0062\p{C}]` does not. That reads as arbitrary until you add
> the JIT result below: the source form selects which compiled path is taken, and only some of
> those are miscompiled. (Verified against the full probe set: **17/59 cases wrong with the JIT,
> 0/59 with `BUN_JSC_useRegExpJIT=0`** — no residual.) Full characterisation and the answers to
> the open questions below: [`bug_reports/REPORT_bun_vmode_class_union_atomicity.md`](bug_reports/REPORT_bun_vmode_class_union_atomicity.md).
> Answered there: BMP-only inputs are **safe**; `g`-mode `lastIndex` **is** corrupted (and feeds
> Bug B). Still open: the oven-sh/bun prior-art search.

**Corpus witness:** `regex_14680` `([\s\t\p{Zl}\p{C}\p{Zp}])` — 587 cases, the 3rd-largest
cluster in the window. Evidence: `/scratch/turcotte/verbal/results/regex_14680/exec.diff.json`
(filter `flags == 'v'`, 44 discrepancies in `exec` alone).

### ⭐ LOCALIZED TO THE JIT (2026-08-03, after the handoff was first written)

**Disabling JavaScriptCore's RegExp JIT makes the bug disappear.** Deterministic, 3/3 runs
each way, and it holds for the original corpus pattern as well as the reduced one:

```
bun vclass.js                        -> len=1  ["U+DB61"]   <- lone high surrogate, WRONG
BUN_JSC_useRegExpJIT=0 bun vclass.js -> len=2  ["U+E8541"]  <- whole code point, CORRECT
```

That the same binary disagrees with itself across tiers makes this a **Yarr JIT
miscompile**, not a front-end or semantics bug — and it establishes which side is wrong
**without any cross-engine vote or spec argument**. "Disabling the RegExp JIT fixes it" is
the single most useful sentence to hand a JSC maintainer, so lead the report with it.

The env var is confirmed to actually take effect, not be silently ignored: the same probe's
timing loop goes from 1ms (JIT) to 59ms (no JIT).

**Impact is far worse than `exec` returning a short match — it TEARS SURROGATE PAIRS APART
in `split` and `replace`.** A tier sweep over `regex_14680`'s harnesses found the JIT/interp
disagreement across **5 APIs** (replace 10, matchAll 7, exec 3, split 3, match 2). The
`split` outputs are the ones to lead a severity argument with:

```
split, bun JIT     ["", "\uda44", "\udc6d"]     <- one code point split into TWO lone surrogates
split, bun no-JIT  ["", "򡁭", ""]     <- correct
```

So the miscompile does not merely return a truncated match: it emits **structurally invalid
UTF-16** into ordinary string-processing output. Any pipeline that splits or replaces on such
a class and then re-encodes gets mojibake or a replacement character. That is a much stronger
severity claim than "astral edge case in `exec`".

**Scope check (2026-08-03):** a stratified sweep of 500 harnesses over the 12 corpus regexes
that combine `\p{...}` with `v` found tier disagreements in **`regex_14680` only** — the
other 11 are clean. A uniform sweep of 600 harnesses across the whole corpus found **zero**.
So this shape is rare in real-world regexes, which argues for severity-by-consequence rather
than severity-by-frequency when writing the report.

**The other two bugs are NOT JIT-specific** — both reproduce identically with the JIT
disabled, so they live in the shared/interpreter path:

| Bug | JIT | no JIT |
|---|---|---|
| v-mode class union (this one) | len 1 ❌ | len 2 ✅ **fixed** |
| sticky + leading `.*` | `null` ❌ | `null` ❌ |
| unicode `lastIndex` surrogate (§3) | index 2 ❌ | index 2 ❌ |

**Open questions before filing:**
- How far does it generalize? Test other overlapping triples (`[\w a \p{L}]`, `[\d 0 \p{N}]`),
  and non-property operands — is `\p{...}` needed at all, or just any 3-operand union?
- Can it produce a wrong result on **BMP-only** input? If yes the severity is much higher than
  "astral edge case".
- Does it also corrupt `lastIndex` advancement (stride 1 vs 2) in `g` mode?
- Search oven-sh/bun for existing v-mode / unicodeSets issues.

**Probe script:** `scratchpad/probe_prop_astral.js`, `scratchpad/probe_vclass_min.js` (see §6).

---

## 3. Bug B — bun unicode-mode `lastIndex` inside a surrogate pair  ⭐ NEW

**This is the real identity of the "34-regex `matchAll`+`gv` bun v-mode bug"** reported in the
previous two windows. It is neither v-specific nor matchAll-specific.

**Minimal repro** (verified 2026-08-03 under all three engines):

```js
const re = /./gu;          // `gv` behaves identically
re.lastIndex = 1;          // points INTO the surrogate pair
re.exec("\u{10437}2");     // units: [0]=D801 [1]=DC37 [2]='2'
```

| Engine | Match | `lastIndex` after |
|---|---|---|
| node v26.5.0 | `"\u{10437}"` at index **0** | 2 |
| deno 2.9.1 | `"\u{10437}"` at index **0** | 2 |
| **bun 1.3.14** | `"2"` at index **2** | 3 |

V8 **backs up** to the start of the code point; JSC **skips forward** past it. Plain `/g`
(non-unicode) agrees across all three engines, so this is purely the unicode-mode index
adjustment.

**Spec reading (verify before filing):** ECMA-262 `RegExpBuiltinExec` matches at "the index into
`input` of the character obtained from element `lastIndex` of S". With `fullUnicode` true,
`input` is a list of *code points*; the character obtained from element 1 is the code point
U+10437, whose index is 0. That makes **node/deno correct and bun wrong** — but read the current
spec text yourself before asserting it in an issue.

> **CORRECTION 2026-08-03 (later the same day) — reading the spec text is what broke this
> conclusion.** The first half holds: `inputIndex` does back up to the code point, supporting
> V8. But `index` and `[[StartIndex]]` are then taken from the *unadjusted* `lastIndex`, so a
> literal application returns a **lone low surrogate at index 1** — a third answer neither V8
> nor JSC produces. The algorithm is internally inconsistent here and TC39 knows:
> [tc39/ecma262#128](https://github.com/tc39/ecma262/issues/128) is **open**, labelled
> *normative change*. So this is an **interop divergence inside an acknowledged spec gap**,
> not a conformance violation, and must not be filed as one. Details, plus the newly found
> `test()`→`false` / sticky→`null` / `matchAll`-drops-a-match consequences:
> [`bug_reports/REPORT_bun_unicode_lastindex_surrogate.md`](bug_reports/REPORT_bun_unicode_lastindex_surrogate.md).
> Confirmed **not** JIT-related (identical 12/107 failures with `BUN_JSC_useRegExpJIT=0`).

**Why it looked like 34 unrelated regexes:** the harness's `chaos_alphabet` contains
`"\u{10437}"` (see `resolved_config` in any headline) and its `lastIndex` presets include 1.
So *any* pattern that can match an astral character reproduces it. **34 witnesses, 1 bug, and
the count says nothing about pattern diversity** — don't cite it as breadth in the report.

**Corpus witness (simplest):** `regex_13775` `[^;]` under `gv` —
`/scratch/turcotte/verbal/results/regex_13775/matchAll.diff.json`, 3 discrepancies.

**Probe script:** `scratchpad/probe_surrogate_lastindex.js`.

---

## 4. Already known — do NOT re-triage

**C. bun sticky (`y`) + leading `.*` → `null`.** 1361 sticky-flagged cases across 8 regexes in
this window (`regex_13813` `^.*\p{Upper}.*$`, `14057` `.*RUNTIME DEBUG.*`, `14862`, `13552`, …),
almost certainly plus the 572 `split` cases in the no-flag bucket (the report already documents
that `split` builds a sticky matcher internally regardless of caller flags).

- Report **already drafted and re-verified against bun 1.3.14 on 2026-07-24**:
  `analysis/bug_reports/REPORT_bun_sticky_dotstar.md`
- 7 earlier witnesses already triaged as VC-01…VC-07 in
  `analysis/potential_findings/CANDIDATES.md` (same `.*<literal>.*` + sticky/split shape).
- This window's 8 regexes are **witnesses 8–15**, not a new bug. Their only real value is
  extra evidence of prevalence if the issue gets pushback.
- **Blocking work is just the filing checklist**, 2 boxes unchecked: search oven-sh/bun for
  prior art, and decide whether the `split` corollary rides along in the same issue.

**D. F001 — deno `\p{...}` tables lag Unicode 17.** 586 cases / 3 regexes (`regex_12788`,
`12190`, `14932`). Report drafted: `REPORT_deno_unicode17_property_tables.md`. Filing venue
still open (may be upstream V8/ICU rather than deno).

---

## 5. Open residue and other threads

- **F — RESOLVED 2026-08-03: a new, third bun bug.** Not a facet of the sticky bug. All 170 cases
  are flag **`gs`**, and the cause is a Yarr JIT miscompile: with `lastIndex` > 0, `/.*X.*/gs`
  matches from index **0** instead of from `lastIndex`. The counts account for the residue
  exactly — `regex_14057` 58 + `regex_14862` 58 + `regex_13552` 54 = **170**.

  The decisive repro: `[\s\S]*X[\s\S]*` under `/g` is correct in bun but wrong under `/gs`,
  and `s` is a **no-op by construction** for `[\s\S]` — so the flag alone changes the answer
  without being able to change the language. `BUN_JSC_useRegExpJIT=0` fixes it (6/16 wrong with
  the JIT, 0/16 without), which also separates it from the sticky-`.*` bug: that one survives the
  flag, so despite sharing the `.*<literal>.*` shape they are different defects and must not be
  merged. Report: [`bug_reports/REPORT_bun_dotall_offset_dotstar.md`](bug_reports/REPORT_bun_dotall_offset_dotstar.md).

  (The same three regexes also carry `gy` discrepancies — *those* are the known sticky bug.)
- **E — ReDoS: triaged 2026-08-03, see
  [`redos_nomination/TRIAGE_12050_15050.md`](redos_nomination/TRIAGE_12050_15050.md).**
  Of the 26 regexes, **13 are structurally incapable of superlinear backtracking** (≤1
  unbounded quantifier, no quantified group) yet all recorded 20s timeouts; in those buckets
  the timeouts are spread uniformly across engines and **never hit more than one engine at a
  time** — random process starvation, not regex behaviour. `regex_14648` (86 of the 239 rows)
  was re-run unloaded: all three engines return the same value (`NULL`), timings are
  bun 3.96s / node 5.84s / deno 5.76s against 15.1s / >20s / >20s in the pool, so the pool
  inflated readings 3–4x and the engine ratio is 1.5x — under the 10x gate, i.e. real ReDoS
  but **not** an engine differential. The one unexamined candidate is `regex_14841`, the only
  nomination in the queue that did not time out. A free static pre-filter (≤1 unbounded
  quantifier ⇒ never nominate) would have dropped 79 rows before queuing.

  Original note: `results/redos_queue_12050_15050.json`, 239 nominations / 26 regexes,
  `regex_14648` alone is 86 of them. `harnesses_missing: 0`, harness source inlined, so the queue
  is portable. **Nothing in it is a finding until a serial, unloaded confirm runs.** The confirm
  consumer was deliberately not built; when building it, emit the existing `redos_<window>.json`
  schema so `dedupe_headline.py` needs no change, gate hard on engine-version match, record the
  confirming box, and add `--shard i/N`. Ratios survive a change of box; absolute ms do not.
- **F002 `regex_5354` bun anchor-hoist** — confirmed reproducible, still needs its
  `DISCREPANCIES.md` section written before it can get a report draft.

---

## 5b. PENDING repo edits — held for provenance, staged on /scratch

Three edits are **finished but not applied**, because their targets are tracked (or, for a
`.py`, untracked-but-not-ignored). Editing either kind shows in `git status --porcelain`, which
is what `config._git_commit` stamps, so doing it while a run is live marks every artifact that
run writes afterwards `-dirty`. (§6 says "*.md is gitignored, which is why this handoff can live
in `analysis/`" — true for *new* files, but `DISCREPANCIES.md`, `EXPERIMENT_GAPS.md`,
`HANDOFF_redos_timing.md`, `HANDOFF_regex_5354.md` and `redos_nomination/NOTES.md` are tracked.
Check with `git ls-files analysis/ | grep '\.md$'`.)

| target | content | state |
|---|---|---|
| `differential_findings/DISCREPANCIES.md` | **F002** catalogued (+ 2026-08-03 re-verify: Yarr JIT miscompile, no symmetric `$` bug, not global-specific) and **F005** — the sticky-`.*` family promoted from VC-01…VC-07, all seven witnesses verified directly, `split` corollary corrected | written, held (+154/−7 lines) |
| `EXPERIMENT_GAPS.md` | **G9** — ReDoS nomination fires on process starvation; sound static pre-filter as the fix | written, held (~+45 lines) |
| `analysis/eval_help_scripts/confirm_redos.py` | add the **static ReDoS pre-filter** (drops 79 of 239 rows / 13 of 26 regexes, soundly) | written, held; **needs the fast-forward first** |

**Staged durably at `/scratch/turcotte/verbal/pending_2026-08-03/`** (not the session scratchpad,
which is `/tmp` and gets cleaned). Apply all three with one command once no run is live — it
refuses otherwise, and `--check` is a dry run:

```bash
docker ps --filter name=verbal_run --format '{{.Names}}'   # must be empty
python3 /scratch/turcotte/verbal/pending_2026-08-03/apply_pending_docs.py
```

### Branch state (checked 2026-08-03) — nothing is upstream

`origin` has only `main` (`b24fca5`, 2026-07-02) and `repo-reorg` (`cab88d0`, 2026-07-21), both
**behind** us; local `repo-reorg` is ahead 10, behind 0. **There is nothing to pull.**

The parallel session's work is a **local second worktree**: `/scratch/turcotte/verbal-dev` on
`expansion-work` (`7335d2f`), 5 commits whose merge-base is exactly our HEAD — a clean
fast-forward, no divergence, and it has not touched our tree. It adds `reduce.py` (ddmin to a
minimal repro), `laws.py` and `tier_diff.py` (oracles needing no cross-engine vote), unit tests,
and an `ENGINE_ENV` per-engine env overlay in `run_engine` whose stated purpose is
`BUN_JSC_useRegExpJIT=0` as a **pseudo-engine**.

> **That overlay matters for today's findings.** Three are JIT-only (Bug A, Bug F, F002) and two
> survive the flag (sticky-`.*`, `lastIndex`-in-surrogate). `tier_diff.py` + `ENGINE_ENV` turns
> today's manual JIT probing into a pipeline oracle, and — as the Bug A report argues — a
> tier differential needs no cross-engine vote to establish ground truth.

> **Duplicate work, resolved.** That branch also committed its own `confirm_redos.py`
> (`analysis/eval_help_scripts/`, 303 lines) while this session independently built one. They
> converged on schema, load gate, version gate, `--shard` and box recording. **Theirs is the
> keeper** — `--force-loaded` stamps `box_loaded` into the artifact, and its `throw_artifacts`
> bucket correctly diagnoses `regex_13150 replaceAll [i]` as a `TypeError` (`replaceAll` needs
> `g`). This session's copy was deleted; only the pre-filter survives, as the patch above.

---

## 6. Environment — how to reproduce anything here

The host has **no node/bun/deno**; everything runs in `verbal:latest`. A run is currently live on
cores 8–47, so **pin probe containers to low cores** and do not mount the repo (avoids any risk of
dirtying the tree, which would taint the live run's provenance):

```bash
docker run --rm --cpuset-cpus 0-3 --memory 2g --memory-swap 2g --entrypoint bash \
  -v <scratchpad>:/probe -w /probe verbal:latest \
  -lc 'node p.js; bun p.js; deno run --quiet p.js'
```

The three probe scripts used for this handoff live at
**`/scratch/turcotte/verbal/probes_2026-08-03/`** — `probe_surrogate_lastindex.js`,
`probe_prop_astral.js`, `probe_vclass_min.js`. Mount that directory as `/probe` in the command
above.

> ⚠️ **They are deliberately NOT in the repo.** `config._git_commit` marks provenance `-dirty`
> from `git status --porcelain`, which **counts untracked files** — so adding any non-gitignored
> file (a `.js` probe, a scratch script) to the working tree while a run is live taints every
> artifact that run writes afterwards. `*.md` is gitignored (`.gitignore:85`), which is why this
> handoff can live in `analysis/`. Keep everything else on `/scratch`.

Evidence layout: `/scratch/turcotte/verbal/results/` holds `eval_headline_<window>.json`,
`redos*_<window>.json`, and per-regex `regex_<id>/<api>.diff.json` (each diff carries full
provenance + engine versions + every engine's raw stdout, so a case can be re-read without
re-running). Cluster view: `python3 analysis/eval_help_scripts/dedupe_headline.py <headline.json>`
— with the two caveats in §1.

---

## 7. Suggested order of work

1. **Bug A** — generalize the trigger (§2 open questions), then draft
   `REPORT_bun_vmode_class_union_atomicity.md` in `analysis/bug_reports/` and add the row to that
   directory's README table.
2. **Bug B** — settle the spec reading, then draft `REPORT_bun_unicode_lastindex_surrogate.md`.
3. **File the backlog.** Four drafted reports are sitting unfiled (three bun + one deno); A and B
   make it six, five of them bun/JSC. The README already suggests filing the bun set as a
   cross-linked batch — that is now the single highest-leverage action in the project.
4. **Triage residue F**, then build the ReDoS confirm consumer (E).
