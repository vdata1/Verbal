# Upstream bug reports — status tracker

> **This directory is the single home for all bug-report texts.** Every ready-to-file
> report draft (`REPORT_*.md`) lives here, regardless of which finding it came from
> (`differential_findings/` confirmed or `potential_findings/` triaged). New drafts go
> here too. Evidence folders stay with their findings; only the report *text* is collected here.

File-ready drafts for the confirmed cross-engine regex bugs. All re-verified against the
**latest** engine releases on 2026-07-24 (`bun:latest` = 1.3.14, `deno:latest` = 2.9.4,
node v26.5.0 reference). **Text only — nothing has been filed.** Post from these drafts
after a final read; each ends with a pre-post checklist (remove before posting).

| Bug | Engine | Venue | Latest re-verify | Draft |
|-----|--------|-------|:----------------:|-------|
| Sticky (`y`) `.*` backtrack → `null` | bun (JSC) | oven-sh/bun | ✅ 1.3.14 still fails | [`REPORT_bun_sticky_dotstar.md`](REPORT_bun_sticky_dotstar.md) |
| `\p{...}` not case-folded under `/i` (F003) | bun (JSC) | oven-sh/bun | ✅ 1.3.14 still fails | [`REPORT_bun_ignorecase_property_escape.md`](REPORT_bun_ignorecase_property_escape.md) |
| Backtracking step-cap → silent `false` (F004) | bun (JSC) | oven-sh/bun | ✅ 1.3.14 still fails | [`REPORT_bun_backtracking_step_cap.md`](REPORT_bun_backtracking_step_cap.md) |
| `\p{...}` tables lag reported Unicode 17.0 (F001) | deno (V8 data) | denoland/deno | ✅ **2.9.4** still fails | [`REPORT_deno_unicode17_property_tables.md`](REPORT_deno_unicode17_property_tables.md) |
| `v`-mode class returns a lone surrogate (Bug A) — **Yarr JIT miscompile** | bun (JSC) | WebKit? / oven-sh/bun | ✅ verified 1.3.14 (2026-08-03) | [`REPORT_bun_vmode_class_union_atomicity.md`](REPORT_bun_vmode_class_union_atomicity.md) |
| `lastIndex` in a surrogate pair (Bug B) — **spec gap, not a clean violation** | bun (JSC) | tc39#128 and/or oven-sh/bun | ✅ verified 1.3.14 (2026-08-03) | [`REPORT_bun_unicode_lastindex_surrogate.md`](REPORT_bun_unicode_lastindex_surrogate.md) |
| `s` flag shifts match start when `lastIndex`>0 (Bug F) — **Yarr JIT miscompile** | bun (JSC) | WebKit? / oven-sh/bun | ✅ verified 1.3.14 (2026-08-03) | [`REPORT_bun_dotall_offset_dotstar.md`](REPORT_bun_dotall_offset_dotstar.md) |

> **Filing pass starts here:** [`FILING_PLAN.md`](FILING_PLAN.md) — venue per report (they are
> *not* all bun), which claims are safe to assert versus hedged, the prior-art searches that block
> every draft, and the three 2026-08-03 corrections that older docs still contradict.

## Notes

- **Six bun / one deno.** Four of the JavaScriptCore bugs could be filed as a coordinated
  batch and cross-linked (independent mechanisms — sticky/`.*` backtrack, `/i` property-escape
  folding, backtracking step-cap, `v`-mode class atomicity — but the same engine and reporter).
  Bug A and Bug B compose: Bug A leaves `lastIndex` inside a surrogate pair, which is Bug B's
  trigger. **Bugs A and F are both Yarr JIT miscompiles** (both vanish under
  `BUN_JSC_useRegExpJIT=0`) and may be worth filing as one investigation; the sticky-`.*` bug
  survives that flag, so despite sharing a pattern shape with F it is a separate defect.
- **Bug B is not like the others — do not batch it thoughtlessly.** Every other report here
  asserts a spec violation. Bug B sits in an *acknowledged spec gap*
  ([tc39/ecma262#128](https://github.com/tc39/ecma262/issues/128), open, "normative change"):
  a literal reading of `RegExpBuiltinExec` produces a third answer that neither V8 nor JSC
  returns. It has to be argued from interop and consequences, and the highest-value venue may
  be tc39 rather than bun. Filing it in a "bun violates the spec" batch invites a fast close.
- **Minimal repros are self-contained one-liners**; no fuzzer or Docker needed to reproduce.
  A combined check lives at `scratchpad/verify4.js` (run under node/bun/deno).
- **F001 filing venue is open** — it may be an upstream V8/ICU data issue rather than
  deno-specific. The self-report inconsistency (deno claims 17.0, ships 16.0 tables) is
  deno's to answer regardless; see the draft's checklist.

## Not yet drafted

- **F002 — `regex_5354` bun anchor-hoist** (bun/JSC). Confirmed-reproducible but **not yet
  written up** as a finding, so no report draft. Needs the `DISCREPANCIES.md` F002 section
  written first (it's unblocked — G6 resolved, artifacts reproduce byte-for-byte). Then it
  can get a report in the same format, likely folded into the bun batch.

## Candidates still in triage (not ready to report)

- **VC-01…VC-07** (the sticky-`.*` family) — the *root cause* is the bun sticky bug above and
  its report is ready; promoting the 7 corpus witnesses into a single `Fxxx` finding is
  bookkeeping that can follow the filing. See
  [`../potential_findings/CANDIDATES.md`](../potential_findings/CANDIDATES.md).
- **RD-01…RD-04** (ReDoS) — engine-specific slowness, **not** yet proven superlinear; need a
  growing-length test family before any are reportable.
