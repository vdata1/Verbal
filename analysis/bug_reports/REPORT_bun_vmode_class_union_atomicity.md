# Bug report (draft) — bun (Bug A): `v`-mode character class returns a lone surrogate

**Target:** [oven-sh/bun](https://github.com/oven-sh/bun/issues) · **Component:** RegExp (JavaScriptCore / Yarr) · **bun 1.3.14** (= `bun:latest`)

> ⚠️ **Correctness-relevant:** bun returns a match string that is **not well-formed UTF-16** — a lone
> high surrogate. Any caller that slices, re-encodes, stores or concatenates the match gets mojibake,
> a replacement character, or a throw from a strict UTF-8 encoder.

---

## Title

`RegExp` with the `v` flag matches only the **high surrogate** of an astral code point, for
character classes in which a `\p{...}` operand is preceded by other operands

## Minimal reproduction

```js
new RegExp("[\\s\\t\\p{C}]", "v").exec("\u{E8541}")
```

| Engine | Result | Length |
|---|---|---|
| Node.js v26.5.0 | `"\u{E8541}"` (`DB61 DD41`) | **2** ✅ |
| deno 2.9.1 | `"\u{E8541}"` (`DB61 DD41`) | **2** ✅ |
| **bun 1.3.14** | `"\uDB61"` — a lone high surrogate | **1** ❌ |

Deterministic: identical across three fresh compiles, a reused `RegExp` object, and separate
processes.

## Disabling the RegExp JIT fixes it — this is a Yarr JIT miscompile

```
bun probe.js                        -> len 1  [DB61]        WRONG
BUN_JSC_useRegExpJIT=0 bun probe.js -> len 2  [DB61 DD41]   CORRECT
```

Across a 59-case probe set, bun gets **17 cases wrong with the JIT enabled and 0 wrong with it
disabled** — every single failure is JIT-only, with no residual. The env var demonstrably takes
effect rather than being ignored (the probe's timing loop goes from ~1 ms to ~59 ms).

**This is the most useful fact in the report, and it should lead the issue.** It means:

- The bug is in the **JIT-compiled** path, not in class parsing, set arithmetic, or semantics —
  the interpreter builds the right set from the same source.
- **Ground truth needs no cross-engine vote and no spec argument.** The same binary disagrees
  with itself across execution tiers; whichever tier is right, they cannot both be, and the
  interpreter's answer is the one that also matches every other engine.

It also explains the otherwise baffling trigger boundary below: which cases get miscompiled
depends on how the class is written, because the source form is what selects the compiled code
path. A miscompile is exactly the kind of defect whose trigger looks arbitrary from outside.

## Why `"\uDB61"` is wrong

Under `v` (`unicodeSets`), matching proceeds over **code points**, not UTF-16 code units — a single
`[...]` atom either consumes the whole code point or does not match. `RegExpBuiltinExec`
(ES2024 §22.2.7.2) builds the result from the matched code-point span, so no conforming
implementation can return half of a surrogate pair for a one-atom class.

**It is not merely a truncated match — the returned unit is not even in the class.** With
`\p{L}` the class contains no surrogates at all, yet bun still returns the high surrogate:

```js
new RegExp("[\\s\\t\\p{L}]", "v").exec("\u{10400}")
//  node/deno -> "\u{10400}"  (D801 DC00), length 2
//  bun       -> "\uD801"     length 1  --  U+D801 is category Cs, NOT \p{L}
```

Same for `[\d0\p{N}]` on `U+1D7CE` (returns `D835`, not a `\p{N}`) and `[\s\t\p{Cn}]` on
`U+E8541` (returns `DB61`, category Cs, not Cn). So this is not "the matcher fell back to a
code-unit view of the same set" — bun returns a code unit that **no reading of the class
contains**.

## Trigger

Three conditions are individually necessary (each has a passing control):

1. **The `v` flag.** Every case below is correct under `u`. `v`-only.
2. **A `\p{...}` operand that is what actually matches.** A range (`[\s\t\u{1F600}-\u{1F610}]`)
   or a bare astral literal (`[\s\t\u{1F600}]`) is correct; so is `[\s\t\u{1F600}\p{C}]` on
   `U+1F600`, where the property is present but the *literal* is what matches. Negated `\P{L}`
   does **not** trigger it.
3. **An astral subject.** All BMP inputs tested — `U+0000 U+0009 U+0020 'a' U+FEFF U+00AD U+2028`,
   and standalone lone surrogates `U+DB61` / `U+DD41` — agree across all three engines.

Beyond that, which classes actually hit the bad codegen is **sensitive to how the class is
spelled**. Identical character sets behave differently:

| Class | bun `/v` | |
|---|---|---|
| `[ab\p{C}]` | **len 1** ❌ | bare literals |
| `[\u0061\u0062\p{C}]` | len 2 ✅ | same set, `\u` escapes |
| `[\x61\x62\p{C}]` | len 2 ✅ | same set, `\x` escapes |
| `[\u{61}\u{62}\p{C}]` | len 2 ✅ | same set, `\u{}` escapes |
| `[\s\t\p{C}]` | **len 1** ❌ | |
| `[\t\s\p{C}]` | len 2 ✅ | **same operands, order swapped** |
| `[\s\u0009\p{C}]` | **len 1** ❌ | escaping the tab does *not* help here |
| `[\u0009\s\p{C}]` | len 2 ✅ | order does |
| `[a\p{C}]` | len 2 ✅ | one preceding operand is fine |
| `[\p{C}\s\t]`, `[\s\p{C}\t]`, `[\p{C}ab]` | len 2 ✅ | property first or second is fine |

Two classes denoting **exactly the same set of code points** give different answers depending on
whether their members are written as bare literals or as escapes, and on the order the operands
appear. Since the interpreter handles every one of these correctly, the source form is not
changing *what set is built* — it is changing **which compiled path the JIT takes**, and only
some of those paths are wrong. Do not read the table above as a semantic rule; read it as a map
of which shapes happen to reach the bad codegen.

A 196-cell sweep of `[\uXXXX\uYYYY\p{C}]` over 14 representative code points found **zero**
failures — consistent with the above: escaped operands never trigger it.

> **Note for triage:** an earlier internal hypothesis was "three operands with an overlapping
> pair" (`\t ⊂ \s`). That is **wrong** — `[ab\p{C}]` fails with disjoint operands, and
> `[\t\s\p{C}]` is correct with the same overlapping pair as the failing `[\s\t\p{C}]`.

## It also corrupts `lastIndex`, and the corruption is self-propagating

```js
const re = new RegExp("[\\s\\t\\p{C}]", "gv");
// subject: "\u{E8541}\u{E8541}"  (four code units)
```

| Engine | Matches |
|---|---|
| node / deno | `@0 [DB61 DD41] → lastIndex 2`, `@2 [DB61 DD41] → lastIndex 4` |
| **bun** | `@0 [DB61] → lastIndex 1`, `@2 [DB61] → lastIndex 3` |

bun leaves `lastIndex` **inside a surrogate pair** (1, then 3). That is precisely the input
condition for the separate bun `lastIndex`-in-a-surrogate-pair bug
([`REPORT_bun_unicode_lastindex_surrogate.md`](REPORT_bun_unicode_lastindex_surrogate.md), Bug B) —
the two compose, and it is Bug B's forward-skip that keeps this loop from degenerating further.
Worth cross-linking if both are filed — but note they are **different kinds of defect**: Bug B
reproduces identically with the JIT disabled, so it lives in the shared path, while this one is
JIT-only.

## Corpus incidence

Found by a differential fuzzing pipeline over a 537k-regex corpus. Witness `regex_14680`
`([\s\t\p{Zl}\p{C}\p{Zp}])` — 587 discrepancy cases in window 12050–15050, the third-largest
cluster. **177 corpus regexes** have the triggering shape (a class with at least one operand
before a `\p{...}`), e.g. `[\d\s\p{L}\.:,%&\/><\-)!|]+`, `([\d\s\p{L}:,\.]{3,})+`,
`[+＋\p{Nd}]` — ordinary text-scanning classes, not exotica.

## Environment

- **Also reproduces on `bun 1.4.0-canary.1+52af83272`** — the Rust rewrite of Bun (merged May 2026,
  canary channel, Linux x64). Behaviour is **byte-for-byte identical to 1.3.14** across the whole
  probe set, which is expected: the rewrite replaced Bun's own runtime code, not JavaScriptCore.
  That is positive evidence the defect lives in **JSC/Yarr**, not in Bun's Zig/Rust layer — i.e. an
  argument for filing at WebKit.
  The tier differential holds on the canary too (17/59 wrong with the JIT, 0/59 with `BUN_JSC_useRegExpJIT=0`).
- **bun 1.3.14** (buggy; = `bun:latest`), vs **Node.js v26.5.0** and **deno 2.9.1**, both correct.
- Verified 2026-08-03 in a pinned container, all three engines in one invocation.
- Probes: `/scratch/turcotte/verbal/probes_2026-08-03/probe_vclass_{generalize,trigger,grid,escape}.js`
- JIT comparison: same probes re-run under `BUN_JSC_useRegExpJIT=0` (17 wrong -> 0 wrong).

---

### Filing checklist (internal — remove before posting)

- [x] Minimal repro reduced to a one-liner, verified on all three engines (2026-08-03).
- [x] **Localized to the Yarr JIT** — 17/59 cases wrong with the JIT, 0/59 without. Lead with this.
- [x] Trigger boundary characterised; handoff's overlap hypothesis falsified.
- [x] Confirmed deterministic (3 compiles + reused object + separate processes).
- [x] Confirmed `v`-only, astral-only, property-must-be-the-matching-operand.
- [ ] Since it is a JIT miscompile, **WebKit (Yarr) is likely the right venue**, not bun — check
      whether bun carries JSC patches here before choosing. This supersedes the last box below.
- [ ] **Verify the exact spec citation** for code-point-wise matching under `v` before asserting
      §22.2.7.2 in the issue text.
- [ ] Search oven-sh/bun for existing `v` / `unicodeSets` / lone-surrogate issues.
- [ ] Decide whether to file jointly with Bug B (they compose via `lastIndex`) or separately.
- [ ] Consider filing upstream at WebKit (Yarr) rather than bun, if bun tracks JSC unmodified.
