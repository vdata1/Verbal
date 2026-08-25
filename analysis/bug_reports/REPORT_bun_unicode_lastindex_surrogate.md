# Bug report (draft) — bun (Bug B): unicode-mode `lastIndex` pointing into a surrogate pair

**Target:** [oven-sh/bun](https://github.com/oven-sh/bun/issues) · **Component:** RegExp (JavaScriptCore / Yarr) · **bun 1.3.14** (= `bun:latest`)

> ⚠️ **Read the spec section before filing.** Unlike the other bun findings in this directory,
> this one is **not a clean conformance violation** — ECMA-262 is genuinely ambiguous here and
> TC39 has an open issue saying so. The case for filing is **interop + consequences**, not
> "bun violates the spec." Framing it as the latter will get it closed. See
> [What the spec actually says](#what-the-spec-actually-says).

---

## Title

Under `u`/`v`, when `lastIndex` points at a trail surrogate, bun skips past the whole code point
where V8 backs up to its start — silently dropping matches and returning `false` from `test()`

## Minimal reproduction

```js
const re = /./gu;          // `gv` behaves identically
re.lastIndex = 1;          // points INTO the pair: units are [0]=D801 [1]=DC37 [2]='2'
re.exec("\u{10437}2");
```

| Engine | Match | `index` | `lastIndex` after |
|---|---|---|---|
| Node.js v26.5.0 | `"\u{10437}"` | 0 | 2 |
| deno 2.9.1 | `"\u{10437}"` | 0 | 2 |
| **bun 1.3.14** | `"2"` | 2 | 3 |

V8 **backs up** to the start of the code point; JSC **skips forward** past it.

## Scope — exactly when it happens

A sweep of every `lastIndex` position over `{ /./, /[^;]/ } × { gu, gv, g, yu, y }` on two
subjects (107 cases) found bun differing in **12**, and every one of them is a `lastIndex`
landing on a **trail surrogate** under `u` or `v`. Specifically:

- **Non-unicode `g`/`y` are unaffected** — this is purely the unicode index adjustment.
- **The advance path is fine.** `AdvanceStringIndex` (the no-match step) strides correctly by
  code points in bun; `/2/gu` from every starting index agrees across all three engines. The
  defect is only in the **initial** `lastIndex` → match-start mapping.
- **`replace` is immune** — a global `replace` resets `lastIndex` to 0 before matching, so it
  never sees a mid-pair value.
- **Not a JIT bug.** Re-running the whole 107-case sweep under `BUN_JSC_useRegExpJIT=0` gives the
  *identical* 12 failures, so this lives in the shared/interpreter path. (Worth stating: the
  sibling finding [`REPORT_bun_vmode_class_union_atomicity.md`](REPORT_bun_vmode_class_union_atomicity.md)
  *is* a Yarr JIT miscompile and vanishes with that flag — so the flag does not blanket-fix
  bun's unicode regexp handling, and the two must not be filed as one defect.)

## Why it is worth fixing regardless of the spec question

The divergence is not confined to a stray `index` value. Three ordinary surfaces silently
produce wrong answers (subject `"a\u{10437}b"`, `lastIndex` = 2):

| Call | node / deno | **bun** |
|---|---|---|
| `re.test(s)` with `/\u{10437}/gu` | `true`, `lastIndex` → 3 | **`false`**, `lastIndex` → 0 |
| `[...s.matchAll(/[^;]/gv)]` | `@1 "\u{10437}"`, `@3 "b"` | **`@3 "b"` only — the astral match is gone** |
| `/[^;]/yu.exec(s)` (sticky) | `"\u{10437}"` at 1 | **`null`** |

`test()` returning `false` is the worst of the three: a boolean surface with no index to
inspect, so a caller cannot tell a real no-match from this. The sticky `null` is the same shape
as bun's other sticky bug in this directory
([`REPORT_bun_sticky_dotstar.md`](REPORT_bun_sticky_dotstar.md)) though the mechanism differs.

**`matchAll` is the realistic entry point.** `String.prototype.matchAll` seeds its internal clone
from the source regexp's `lastIndex`, so any code that reuses a regexp object — the common
`lastIndex` footgun — carries a mid-pair index straight into the iteration and loses a match.

## What the spec actually says {#what-the-spec-actually-says}

`RegExpBuiltinExec` (ECMA-262, `sec-regexpbuiltinexec`, text as of the current draft):

```
1. If fullUnicode is true, let input be StringToCodePoints(string); else ...
1. Repeat, while matchSucceeded is false,
   1. Let inputIndex be the index into input of the character that was obtained
      from element lastIndex of string.
   1. Let result be matcher(input, inputIndex).
   ...
1. Perform ! CreateDataPropertyOrThrow(array, "index", 𝔽(lastIndex)).
1. Let match be the Match Record { [[StartIndex]]: lastIndex, [[EndIndex]]: endIndex }.
```

Apply that literally to the repro. `input` is `[U+10437, U+0032]`. Element 1 of `string` is the
trail surrogate `DC37`, which was obtained from `input[0]`, so `inputIndex` is **0** and the
matcher starts at the code point — that much supports V8. **But `index` and `[[StartIndex]]` are
then taken from the unadjusted `lastIndex` (= 1)**, and `GetMatchString` returns the substring
from `[[StartIndex]]` to `[[EndIndex]]`, i.e. `string[1..2]` = `"\uDC37"`.

So a literal reading yields a **lone low surrogate at index 1** — a third answer that *neither*
V8 nor JSC produces. The algorithm is internally inconsistent for a mid-pair `lastIndex`, and
TC39 knows: [tc39/ecma262#128](https://github.com/tc39/ecma262/issues/128), *"Unicode RegExp with
index points trail surrogate in surrogate pair is not covered in the spec"* — **still open**, and
labelled *normative change*.

**Therefore:** V8 resolves the gap by treating the match as starting at the code-point boundary
(self-consistent, and what MDN and real-world code such as the VS Code find-widget fix assume);
JSC resolves it by skipping the pair. Neither follows the literal text. The ask on bun is to
**match V8 for interop**, not to fix a conformance violation.

> **Correction to internal notes.** `HANDOFF_2026-08-03_new_bugs.md` §3 concluded "that makes
> node/deno correct and bun wrong." That overstates it — the spec does not settle the question,
> and the handoff's own instruction to read the current text before asserting it is what turned
> this up.

## Corpus witness

Found by a differential fuzzing pipeline over a 537k-regex corpus. Witness `regex_13775` `[^;]`
under `gv` — 3 discrepancies in `matchAll` (window 12050–15050).

Note the harness dependency: `matchAll` **from a clean state agrees across all three engines**.
The corpus witness diverges only because the harness's `lastIndex` presets include values that
land mid-pair, and its `chaos_alphabet` contains `"\u{10437}"`. Any pattern that can match an
astral character reproduces it, which is why this surfaced as "34 unrelated regexes" in earlier
windows — **34 witnesses, one bug**; the count says nothing about pattern diversity and should
not be cited as breadth.

## Environment

- **Also reproduces on `bun 1.4.0-canary.1+52af83272`** — the Rust rewrite of Bun (merged May 2026,
  canary channel, Linux x64). Behaviour is **byte-for-byte identical to 1.3.14** across the whole
  probe set, which is expected: the rewrite replaced Bun's own runtime code, not JavaScriptCore.
  That is positive evidence the defect lives in **JSC/Yarr**, not in Bun's Zig/Rust layer — i.e. an
  argument for filing at WebKit.
- **bun 1.3.14** (buggy; = `bun:latest`), vs **Node.js v26.5.0** and **deno 2.9.1**, which agree
  with each other on every one of the 107 sweep cases.
- Verified 2026-08-03 in a pinned container, all three engines in one invocation.
- Probes: `/scratch/turcotte/verbal/probes_2026-08-03/probe_lastindex_{sweep,apis}.js`

---

### Filing checklist (internal — remove before posting)

- [x] Minimal repro verified on all three engines (2026-08-03).
- [x] Scope pinned: trail-surrogate `lastIndex` only, `u`/`v` only, advance path unaffected,
      `replace` immune.
- [x] Consequences established on `test` / `matchAll` / sticky `exec`.
- [x] **Spec question settled — and it does NOT say what the handoff assumed.** Current text is
      internally inconsistent here; tc39/ecma262#128 open, labelled normative change.
- [ ] Decide the venue and framing. Options: (a) file on bun as an **interop** issue arguing from
      consequences + V8 parity; (b) comment on tc39/ecma262#128 with the three-way divergence as
      fresh evidence the gap is real and now observable in shipping engines; (c) both.
      **(b) is arguably the higher-value contribution** — the issue has sat open, and a concrete
      "here are three engines producing three different answers, one of them from the literal
      text" is exactly what would move it.
- [ ] Check test262 for any test covering a mid-pair `lastIndex` (couldn't search it here — `gh`
      is unauthenticated on this box). If a test exists, whichever behavior it encodes settles
      the interop argument immediately.
- [ ] Cross-link Bug A: `[\s\t\p{C}]/gv` leaves `lastIndex` mid-pair, which is this bug's trigger.
      They compose.
