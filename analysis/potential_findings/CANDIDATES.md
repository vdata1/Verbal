# Potential findings — untriaged cross-engine candidates

Staging catalog for the sibling of [`../differential_findings/`](../differential_findings/).
Everything here is **UNCONFIRMED**: a signal the pipeline raised that has *not yet* been
triaged into "real cross-engine bug" vs. "oracle / normalization artifact on our side."

A candidate leaves this file in one of two directions:

- **Promote** → write it up in `../differential_findings/DISCREPANCIES.md` with an evidence
  folder, and assign it an `Fxxx` id. (That file is the record of confirmed bugs.)
- **Drop** → mark it **Rejected** below with a one-line reason (oracle bug, spec-legal
  divergence, measurement artifact) so we don't re-triage it next window.

Nothing here has an evidence folder yet — evidence is *pulled during triage*, once we
know which diverging output is worth freezing. Until then each candidate points at the
raw harnesses under the run's results tree.

> **Provenance caveat inherited from the whole run:** this window's artifacts recorded
> `git_commit: "unknown-CalledProcessError"` (in-container `git` failed on the mounted
> `/work`). Nothing below is pinned to a commit. Re-confirm against a pinned re-run
> before promoting anything.

Engines pinned (Docker `verbal:latest`): **node v26.5.0, bun 1.3.14, deno 2.9.1**.

**Source run:** `regen_6000`, corpus slice 6000–10050, finished 2026-07-22 (exit 0,
`complete: true`, 25072/25072 units). Flag set `"" i m s y d g`.
**Raw results:** `/scratch/turcotte/verbal/results/` (moved off-repo; see
`WHERE_ARE_RESULTS.md`). Headline: `eval_headline_6000_10050.json`;
ReDoS: `redos_6000_10050.json`.

---

## Index

### Value discrepancies — engines ran clean but returned different results

| ID | regex_id | Pattern | Rows | Dominant api / flag | Suspected class | Status |
|----|----------|---------|-----:|---------------------|-----------------|--------|
| [VC-01](#vc-01) | regex_9980 | `^.*@.*丁丁.*$` | 628 | split / `y` | bun sticky-`.*` bug | **Triaged → promote** (verified) |
| [VC-02](#vc-02) | regex_6663 | `.*\*\/.*` | 622 | split / `y` | bun sticky-`.*` bug | **Triaged → promote** (verified) |
| [VC-03](#vc-03) | regex_8195 | `.*\]\]>.*` | 605 | split / `y` | bun sticky-`.*` bug | Triaged (spot-check pending) |
| [VC-04](#vc-04) | regex_7554 | `^.*codename.*$` | 551 | split / `y` | bun sticky-`.*` bug | Triaged (spot-check pending) |
| [VC-05](#vc-05) | regex_8841 | `.*app-only.*` | 524 | split / `y` | bun sticky-`.*` bug | Triaged (spot-check pending) |
| [VC-06](#vc-06) | regex_6071 | `.*not support.*` | 501 | split / `y` | bun sticky-`.*` bug | Triaged (spot-check pending) |
| [VC-07](#vc-07) | regex_9198 | `.*Cisco Adaptive Security Appliance.*` | 346 | split / `y` | bun sticky-`.*` bug | **Triaged → promote** (verified) |
| [VC-08](#vc-08) | regex_10020 | `(([\w#:.~>+()\s-]+\|\*\|\[.*?\])+)\s*(,\|$)` | 1 | exec / `m` | isolated; also RD-04 | Untriaged |

### ReDoS — one engine catastrophically slower than the others

| ID | regex_id | Pattern | Slow engines | Fast | Worst serial | Status |
|----|----------|---------|--------------|------|-------------:|--------|
| [RD-01](#rd-01) | regex_6580 | `#define\s+(\S+)+\s+(\S+)` | node, deno (20s timeout) | bun ~1.3s* | node/deno >20s | Untriaged |
| [RD-02](#rd-02) | regex_8683 | `=\sVersion\s((\d+\.?)+).+?=` | node, deno (20s timeout) | bun ~1–14s | node/deno >20s | Untriaged |
| [RD-03](#rd-03) | regex_9577 | `^(\.?\w+)*$` | node, deno (20s timeout) | bun ~15s | node/deno >20s | Untriaged |
| [RD-04](#rd-04) | regex_10020 | `(([\w#:.~>+()\s-]+\|\*\|\[.*?\])+)\s*(,\|$)` | node, deno (20s timeout) | bun (runs to 20s) | all slow | Untriaged |

\* bun is fast on `exec`/`match`/`test` but itself hits ~17–19s on `replace` for RD-01 — slowness is api-dependent, not a clean "bun is immune" story.

### Explicitly excluded — already confirmed elsewhere, do NOT re-file here

- **regex_8576** (`(\p{L})@`, 182 rows) and **regex_9921** (`\p{Uppercase_Letter}`, 91 rows)
  are already cataloged as **F001 / F003** in
  [`../differential_findings/DISCREPANCIES.md`](../differential_findings/DISCREPANCIES.md).
  They surface again in this window as expected re-witnesses, not new candidates.

---

## VC-01…VC-07 — PROMOTED 2026-08-03 to [F005](../differential_findings/DISCREPANCIES.md#f005)

> **Done.** All seven witnesses were verified **directly** (not by shape) on 2026-08-03, closing
> the "spot-check one before the final writeup" condition below. The family is now catalogued as
> **F005**. Two corrections came out of that run, both carried into the finding:
>
> 1. **The `split` corollary's mechanism below is wrong.** `split` does *not* diverge "regardless
>    of the caller's flags" — plain `"zzx".split(/.*x.*/)` agrees in all three engines, as do all
>    *numeric* limits. The trigger is a `limit` argument that is **not already a number**
>    (`"2"`, `"02"`, `" 2"`, `"2e0"`, `{valueOf:()=>2}`). The harness's limit battery contains the
>    string `"2"`, which is how the corpus reached it. bun returns `["zz",""]`, not "the whole
>    string as a single element".
> 2. **It is not a JIT bug** — identical under `BUN_JSC_useRegExpJIT=0`, unlike the two Yarr JIT
>    miscompiles found the same day. Do not merge it with the dotAll-offset bug despite the shared
>    `.*<literal>.*` shape.

### Original triage (kept for the record)

## VC-01…VC-07 — TRIAGED: real bun sticky-flag bug (V8+deno vs JSC) → promote

**Verdict (2026-07-24): this is a genuine cross-engine bug in bun, not an oracle artifact.**
My earlier "lean oracle-artifact" guess below was **wrong** — the engines really do disagree.

**What the engines return.** For a `.*`-leading pattern under the sticky (`y`) flag, on an
input that has a match beginning at position 0:

| pattern | no flags | `y` (sticky) |
|---------|----------|--------------|
| `^.*@.*丁丁.*$` (VC-01) | node/bun/deno all match `len 49 @0` | node ✓, deno ✓, **bun → no match** |
| `.*\*\/.*` (VC-02) | all match `len 31 @0` | node ✓, deno ✓, **bun → no match** |
| `.*Cisco…Appliance.*` (VC-07) | all match `len 54 @0` | node ✓, deno ✓, **bun → no match** |

**Why bun is wrong (spec-backed).** Sticky only requires the match to *begin* at `lastIndex`
(=0 here). A match anchored at 0 provably exists — node, deno, and bun-without-`y` all find
it. bun's sticky path returns `null` anyway. That is unsound.

**Why `split` is the dominant symptom.** `String.prototype.split(re)` builds a sticky
internal matcher regardless of the caller's flags, so bun's broken `y` path corrupts `split`
results even on the non-`y` rows — returning `[<whole string>]` where node/deno correctly
split. This is exactly the profile every VC member shows (~300 `split` rows, `y`-dominated).

**Root cause shape:** a **leading `.*`** matched under **sticky**, where greedy `.*` runs to
end-of-string and must backtrack to satisfy the rest of the pattern. Independent of the
`^…$` anchors (VC-02/VC-07 are unanchored and reproduce identically). Same engine family as
the confirmed F002/F003/F004 findings — **V8 (node) + deno vs JavaScriptCore (bun)** — but a
distinct mechanism (sticky/`.*`, not the F004 backtracking cap: under no flags bun matches
fine, so this is not a step-budget bailout).

**Evidence gathered** (3 capped `docker run --rm --cpus=1` probes on 2026-07-24):
- VC-01 `split`/`y`: node/deno `["",""]`, bun `[<whole input>]`.
- exec/test probe, VC-01: bun `y`→`test:false` while `(none)`→`test:true, len 49`.
- exec probe, VC-02 & VC-07 (unanchored): bun `y`→`NULL`, `(none)`→full match.

**Confidence & remaining work before promotion to `Fxxx`:**
- Directly verified: **VC-01, VC-02, VC-07** (3 of 7). VC-03/04/05/06 share the exact
  `.*`-leading shape and split/`y` profile — expected same cause; spot-check one before the
  final writeup.
- Minimal repro — **confirmed 2026-07-24** (capped `docker run`):
  ```js
  new RegExp(".*x.*", "y").exec("zzx")
  //  node v26.5.0 → ["zzx"] @0   deno 2.9.1 → ["zzx"] @0   bun 1.3.14 → null  ✗
  ```
  Trigger is a greedy leading `.*` that **overshoots and must backtrack** under sticky:
  `.exec("x")` (no overshoot) matches in all three engines; `.exec("zzx")` (`.*` eats
  `zzx`, backtracks to `zz` so `x` can match) is where bun returns `null`. Non-sticky is
  correct in bun; `/.+x/y.exec("x")` is a true no-match all three agree on. → bun is wrong.
- Ready-to-file upstream report drafted: [`../bug_reports/REPORT_bun_sticky_dotstar.md`](../bug_reports/REPORT_bun_sticky_dotstar.md).
- Then promote the family as a single finding with one evidence folder + minimal repro.

<details><summary>Original (pre-triage) hypothesis — kept for the record; superseded above</summary>

Lean toward **oracle-artifact until proven otherwise**: cross-engine `split` semantics are
tightly specified, so seven clean engine-level `split` bugs of the same shape in one window
is a priori unlikely.

_Superseded:_ the engines were run head-to-head and genuinely disagree; bun is the outlier.
</details>

> **Correction to the run summary.** `regen_6000_summary.md` calls VC-06 (regex_6071) "501
> rows, all `y`-flag `exec`." The artifact says otherwise: 303 `split` rows vs. 38 `exec`,
> flag `y`=239. VC-06 is split-dominated like its six siblings — it is **not** a distinct
> sticky-`exec` cluster. Treat the seven as one family.

---

## VC-01 — regex_9980 `^.*@.*丁丁.*$` {#vc-01}

- **Rows:** 628. **apis:** split 357, exec 46, replace 46, match 45, matchAll 45, test 45, search 44.
- **flags:** `y` 277, then ~51 each of (none)/d/g/i/m/s, `gy` 45.
- **Trigger:** anchored `.*`+CJK literal (`丁丁`) under the sticky flag; `split` divergence dominates.
- **Raw harnesses:** `/scratch/turcotte/verbal/results/regex_9980/` (per-api/case/flag `.js` files).
- **Concrete reproducer** — `regex_9980/split__9__y.js`, the sweep that diverges:
  ```js
  const pattern = "^.*@.*\u4e01\u4e01.*$";   // ^.*@.*丁丁.*$
  const flags   = "y";
  const input   = "\\`D1\u0017B\u0003\u0015\tw[\u0012/Al@\u001er@\u000b…\u4e01\u4e01#…";
  input.split(re);                                  // default
  for (const L of [undefined,0,1,1000000,-1,2**32,2**32-1,1.5,NaN,"2"])
    input.split(re, L);                             // the harness also sweeps `limit`
  ```
- **Triage question:** does node/bun/deno actually return different `split` arrays here, or
  does the divergence live in one of the exotic `limit_*` variants / our `enc()` of the
  result? Pull the three engines' raw stdout for this harness and diff by hand.

## VC-02 — regex_6663 `.*\*\/.*` {#vc-02}

- **Rows:** 622. **apis:** split 364, test 54, replace 53, search 51, exec 50, match 48, matchAll 2.
- **flags:** `y` 308, ~52 each of (none)/d/g/i/m/s, `gy` 2.
- Same `.*<literal>.*` + sticky/split shape as VC-01. Almost certainly resolves together with it.
- **Raw:** `/scratch/turcotte/verbal/results/regex_6663/`.

## VC-03 — regex_8195 `.*\]\]>.*` {#vc-03}

- **Rows:** 605. **apis:** split 343, match 54, test 53, replace 52, search 52, exec 51 (no matchAll).
- **flags:** `y` 311, ~49 each of (none)/d/g/i/m/s.
- **Raw:** `/scratch/turcotte/verbal/results/regex_8195/`.

## VC-04 — regex_7554 `^.*codename.*$` {#vc-04}

- **Rows:** 551. **apis:** split 306, matchAll 44, exec 42, search 41, match 40, replace 39, test 39.
- **flags:** `y` 244, `gy` 44, ~43 each of the rest.
- **Raw:** `/scratch/turcotte/verbal/results/regex_7554/`.

## VC-05 — regex_8841 `.*app-only.*` {#vc-05}

- **Rows:** 524. **apis:** split 305, exec 49, test 47, search 43, replace 41, match 39 (no matchAll).
- **flags:** `y` 262, ~43 each of the rest.
- **Raw:** `/scratch/turcotte/verbal/results/regex_8841/`.

## VC-06 — regex_6071 `.*not support.*` {#vc-06}

- **Rows:** 501. **apis:** split 303, match 44, test 40, replace 39, exec 38, search 35, matchAll 2.
- **flags:** `y` 239, ~43 each of the rest, `gy` 2.
- **Note:** the run summary mislabels this as "all `y`-flag `exec`" — see the correction
  above. It is split-dominated, same family as VC-01…VC-05.
- **Raw:** `/scratch/turcotte/verbal/results/regex_6071/`.

## VC-07 — regex_9198 `.*Cisco Adaptive Security Appliance.*` {#vc-07}

- **Rows:** 346. **apis:** split 193, match 33, search 31, exec 30, replace 30, test 27, matchAll 2.
- **flags:** `y` 178, ~27 each of the rest, `gy` 2.
- Lowest-volume member of the `.*`+sticky/split family; same suspected root cause.
- **Raw:** `/scratch/turcotte/verbal/results/regex_9198/`.

## VC-08 — regex_10020 `(([\w#:.~>+()\s-]+|\*|\[.*?\])+)\s*(,|$)` {#vc-08}

- **Rows:** 1 — a single `exec` divergence under flag `m`. Anomalous compared to the family above.
- **Cross-ref:** this same regex is also **RD-04**, a ReDoS candidate. The lone `exec`/`m`
  discrepancy row may be a boundary of the same catastrophic-backtracking behavior (one
  engine bailed / truncated where another kept going) rather than a value bug — check
  whether the diverging engine was near its step/time budget.
- **Raw:** `/scratch/turcotte/verbal/results/regex_10020/`.

---

## RD-01 — regex_6580 `#define\s+(\S+)+\s+(\S+)` {#rd-01}

- **Shape:** nested `(\S+)+` — textbook exponential backtracking trigger.
- **Profile:** node & deno hit the 20s serial timeout; bun ~1.3s on exec/match/test but
  itself ~17–19s on `replace`. Engine ratio is real but **not proven superlinear** — the
  fuzz inputs are a fixed length, not a growing-length family.
- **Triage → promote path:** build a growing-length input family (per the
  `redos-tracker-needs-long-strings` approach), measure time vs. length, and only then call
  it ReDoS vs. "constant-factor engine slowness." Ground truth from Python `re` timing.
- **Raw:** `/scratch/turcotte/verbal/results/regex_6580/`; timings in `redos_6000_10050.json`.

## RD-02 — regex_8683 `=\sVersion\s((\d+\.?)+).+?=` {#rd-02}

- **Shape:** nested `((\d+\.?)+)` + trailing `.+?=`.
- **Profile:** node & deno time out; bun ranges ~1s (`test`) to ~14s (`split`). **Note an
  inversion:** at least one `test` case (n=52) flips — node ~1.3s / deno ~1.0s **run**, bun
  ~0.15s — i.e. all three finish, no timeout. So the "node/deno slow" story is
  input-specific, not universal for this regex. Worth isolating which inputs flip it.
- **Raw:** `/scratch/turcotte/verbal/results/regex_8683/`.

## RD-03 — regex_9577 `^(\.?\w+)*$` {#rd-03}

- **Shape:** `^(\.?\w+)*$` — classic nested-star over an anchored line; the canonical ReDoS
  shape and the cleanest promotion candidate of the four.
- **Profile:** node & deno time out at 20s across exec/match/matchAll/replace/replaceAll/
  search/split/test; bun ~15s. Broadest api spread of the ReDoS set.
- **Raw:** `/scratch/turcotte/verbal/results/regex_9577/`.

## RD-04 — regex_10020 `(([\w#:.~>+()\s-]+|\*|\[.*?\])+)\s*(,|$)` {#rd-04}

- **Shape:** nested `+` over an alternation containing `.*?` — a CSS-selector-ish pattern.
- **Profile:** node & deno time out; bun also runs to the 20s ceiling (`max_bun_serial ≈
  20000ms`) — the one candidate where **no** engine is comfortably fast, so a growing-length
  family should show superlinearity across all three.
- **Cross-ref:** also **VC-08** (1 `exec`/`m` value discrepancy). Triage the two together.
- **Raw:** `/scratch/turcotte/verbal/results/regex_10020/`.

---

## Suggested triage order

1. **VC-01…VC-07 as one batch** — pull node/bun/deno raw stdout for one `split`/`y` harness
   (start with VC-01) and settle the oracle-vs-engine question once. If it's an oracle
   artifact, all seven drop together and we harden the sticky/split oracle.
2. **RD-03** (`^(\.?\w+)*$`) — cleanest ReDoS shape; first to try promoting with a
   growing-length family.
3. **RD-04 / VC-08** together — the shared regex where every engine is slow and a lone value
   discrepancy overlaps.
4. **RD-01, RD-02** — resolve the api-dependent / input-dependent timing inversions before
   claiming either as ReDoS.
