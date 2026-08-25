# Bug report (draft, ready to file) — bun (F004): backtracking step-cap silently returns "no match"

**Target:** [oven-sh/bun](https://github.com/oven-sh/bun/issues) · **Component:** RegExp (JavaScriptCore / Yarr) · **bun 1.3.14** (= `bun:latest`)

> ⚠️ **Security-relevant:** a backtracking cap meant to *prevent* ReDoS here turns a slow match into a **silent false negative** — a validator/filter/sanitiser can be bypassed by making the input long enough.

---

## Title

`RegExp` returns `false` / `null` for an input that *does* match, once backtracking exceeds an internal step budget

## What happens

For a pattern that requires heavy backtracking, bun abandons the search past an internal step budget and returns a **genuine-looking no-match** — indistinguishable from a real `false`. The match exists (an unanchored pattern reaches it from a late start position), and both V8 and an independent implementation (Python `re`) find it.

## Minimal reproduction

```js
const re = /(a+)+$/;                 // unanchored: the trailing "aaa" always matches
re.test("a".repeat(26) + "!aaa");    // a match exists for every n
```

| n | Node.js v26.5.0 | deno 2.9.4 | **bun 1.3.14** |
|--:|-----------------|------------|----------------|
| 24 | `true` (2.2s) | `true` (1.7s) | `true` (0.23s) |
| 25 | `true` (4.4s) | `true` | `true` (0.45s) |
| **26** | **`true`** (8.8s) | **`true`** (7.0s) | **`false`** (0.68s) |
| 28…100 | timeout | timeout | **`false`** (~0.68s, flat) |

Past n≈26 bun's answer no longer depends on the input — it plateaus at ~0.68s and stays `false` out to n=100+.

## Why `false` is wrong

`(a+)+$` is **not** anchored at the start, so it matches the trailing `aaa` regardless of what precedes it — the correct answer is `true` for every n. ES2024 §22.2.7.2 `RegExpBuiltinExec` defines matching as a total function returning a match iff one exists; `test` is `exec !== null`. There is no resource-limit escape hatch in the matching semantics.

**A `RangeError` would be defensible; a silent `false` is not.** Implementations may fail on resource exhaustion — but bun does not *signal* exhaustion, it returns a value indistinguishable from a genuine no-match, so no caller can tell the difference. bun even has the answer within reach: n=25 → `true` in 0.45s, n=26 → gives up at 0.68s. Only the step budget changed.

Ground truth is not merely "node and deno agree" (both are V8): it's (a) the regex's own semantics — an unanchored search reaches the trailing `aaa` from start position n+1 whatever precedes it — and (b) Python `re`, an independent engine, which matches `'aaa'` at every n small enough to finish.

## The budget is in steps, not milliseconds

The plateau is reproducible per-pattern (not host-timing lore): `/(a+)+$/` gives up at a fixed step count, surfacing as a ~0.68s wall on this hardware. A real corpus regex (`regex_3910`) hits the same cap.

## Environment

- bun 1.3.14 (buggy; = `bun:latest`, re-verified 2026-07-24), vs Node.js v26.5.0 and deno 2.9.4 (both correct), and Python `re` as an independent oracle.
- Found while validating a ReDoS timing-vs-length method; `/(a+)+$/` is synthetic, `regex_3910` is a real corpus row reaching the same cap.

---

### Filing checklist (internal — remove before posting)

- [x] Re-verified on `bun:latest` (1.3.14) — still `false` at n=26 (2026-07-24).
- [ ] Decide framing: file as a **correctness/soundness** bug (silent wrong answer), leading with the security bypass angle. Maintainers may consider the cap intentional — the ask is that exhaustion be *signalled* (throw) rather than returned as `false`.
- [ ] Search oven-sh/bun issues for existing backtracking-limit / step-budget reports.
- [ ] Local evidence: `analysis/differential_findings/bun_backtrack_cap__unsound_step_limit/` (three probes + verbatim output).
