# Filing plan — six drafts, three venues

**Prepared:** 2026-08-03. **Nothing has been filed.** This exists so the filing pass can start
cold: what each report claims, where it should go, what is verified versus hedged, and what is
still unchecked. The drafts themselves are in this directory; read them, not this summary, before
posting. **The user files; do not open issues.**

---

## 1. Venue is not uniform — this is the main thing to get right

Filing all six as "bun bugs" would be wrong for at least three of them.

| # | Report | Engine | Venue | Why |
|---|--------|--------|-------|-----|
| A | [`REPORT_bun_vmode_class_union_atomicity.md`](REPORT_bun_vmode_class_union_atomicity.md) | bun/JSC | **WebKit (Yarr)** likely, else oven-sh/bun | Vanishes under `BUN_JSC_useRegExpJIT=0` → JIT codegen, not bun |
| F | [`REPORT_bun_dotall_offset_dotstar.md`](REPORT_bun_dotall_offset_dotstar.md) | bun/JSC | **WebKit (Yarr)** likely | Same: JIT-only |
| — | F002 (catalogued in `DISCREPANCIES.md#f002`, no draft yet) | bun/JSC | **WebKit (Yarr)** likely | Same: JIT-only |
| B | [`REPORT_bun_unicode_lastindex_surrogate.md`](REPORT_bun_unicode_lastindex_surrogate.md) | bun/JSC | **tc39/ecma262#128** and/or oven-sh/bun | Acknowledged spec gap, not a clean violation |
| C | [`REPORT_bun_sticky_dotstar.md`](REPORT_bun_sticky_dotstar.md) | bun/JSC | oven-sh/bun | Survives the JIT flag → shared path; ordinary soundness bug |
| — | [`REPORT_bun_backtracking_step_cap.md`](REPORT_bun_backtracking_step_cap.md) (F004) | bun/JSC | oven-sh/bun | Step budget, not a JIT tier issue |
| — | [`REPORT_deno_unicode17_property_tables.md`](REPORT_deno_unicode17_property_tables.md) (F001) | deno/V8 data | denoland/deno, possibly upstream V8/ICU | Venue still open in the draft |

**Check first whether bun carries JSC patches in this area.** If it ships JSC unmodified, A/F/F002
belong at WebKit and filing them against bun wastes everyone's time. If it does patch, file at bun
and cross-link.

**Batching.** A, F and F002 are all Yarr JIT miscompiles found the same day and are plausibly one
investigation for a maintainer — consider filing them together. **Do not batch C or B with them**:
C survives the JIT flag despite sharing a `.*<literal>.*` shape with F, and B is not a conformance
violation at all. `bug_reports/README.md` has the same warning.

## 2. Strength of each claim — what is safe to assert

**Strongest, assert freely.** A, F and F002 each have a tier differential: the *same binary*
disagrees with itself between the JIT and the interpreter. That settles ground truth without any
cross-engine vote and without a spec argument. Lead every one of those reports with the
`BUN_JSC_useRegExpJIT=0` line.

- A: 17/59 probe cases wrong with the JIT, 0/59 without.
- F: 6/16 wrong with, 0/16 without. Also has the killer framing — `[\s\S]*X[\s\S]*` is correct
  under `/g` and wrong under `/gs`, and `s` is a **no-op by construction** for `[\s\S]`.
- F002: 9/18 wrong with, 0/18 without.

**Strong, spec-backed.** C (sticky) — sticky requires only that the match *begin* at `lastIndex`;
all seven witnesses verified directly, control `/.+x/y` on `"x"` correctly `null` everywhere.
F004 — ES2024 §22.2.7.2 defines matching as total; a silent `false` is indefensible even if the
cap is intentional (the ask is that exhaustion be *signalled*).

**Hedged — do not overclaim.** B is an **interop divergence inside an acknowledged spec gap**. A
literal reading of `RegExpBuiltinExec` returns a lone low surrogate — a third answer neither V8
nor JSC produces — and [tc39/ecma262#128](https://github.com/tc39/ecma262/issues/128) is open and
labelled *normative change*. Framing it as "bun violates the spec" will get it closed. Argue from
consequences (`test()` → `false`, `matchAll` drops a match, sticky → `null`) and V8 parity.

## 3. Unchecked boxes — the same one blocks all six

**Prior art has not been searched for a single report.** That is the top task:

- oven-sh/bun issues — sticky/`lastIndex`, `v`/unicodeSets, dotAll, backtracking step limit,
  `\p{...}` case folding.
- WebKit Bugzilla (Yarr) — the three JIT miscompiles especially.
- tc39/ecma262#128 — read the full comment thread before adding to it; the fetch used here
  returned only the opening post.
- test262 — is there a test for a mid-pair `lastIndex`? If one exists, whichever behaviour it
  encodes settles B's interop argument immediately. `gh` was unauthenticated on this box, so this
  was not searched.

Other open items, per report: A needs the spec citation for code-point-wise matching under `v`
verified before asserting §22.2.7.2; B needs the venue decision (tc39 vs bun vs both); F001's
venue is still open; F002 has no report draft yet (it is catalogued in `DISCREPANCIES.md` but has
never been written up in this directory's format).

## 4. Corrections made 2026-08-03 — older docs still contradict them

A fresh reader may hit the stale versions first. All three are annotated in place, but know them:

1. **Bug A's trigger** — the handoff's "three operands with an overlapping pair" is falsified
   (`[ab\p{C}]` fails with disjoint operands; `[\t\s\p{C}]` is fine with the same overlapping
   pair). And it is *not* a lost code-point stride: `[\s\t\p{L}]` returns `\uD801`, a code unit
   the class does not contain.
2. **Bug B's spec reading** — the handoff's "that makes node/deno correct and bun wrong"
   overstates it; see §2 above.
3. **The `split` corollary (C/F005)** — `CANDIDATES.md` says split diverges "regardless of the
   caller's flags". It does not. Plain `"zzx".split(/.*x.*/)` agrees everywhere, as do all
   *numeric* limits. The trigger is a `limit` that is **not already a number** (`"2"`, `"02"`,
   `" 2"`, `"2e0"`, `{valueOf:()=>2}`), and bun returns `["zz",""]`, not the whole string.

## 5. Reproducing anything here

Every probe is on `/scratch/turcotte/verbal/probes_2026-08-03/`, runnable in one container
invocation across all three engines (see the handoff §6 for the pinned `docker run`). All minimal
repros are self-contained one-liners; no fuzzer, no corpus, no Docker strictly required.

Engines pinned: **node v26.5.0, bun 1.3.14 (= `bun:latest`), deno 2.9.1**. Re-verify against the
current `bun:latest` before posting — the existing drafts were re-verified 2026-07-24, and A/B/F
on 2026-08-03.
