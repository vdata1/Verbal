# Bug report (draft, ready to file) — bun: sticky (`y`) regex fails to match when a leading `.*` must backtrack

**Target:** [oven-sh/bun](https://github.com/oven-sh/bun/issues) · **Component:** RegExp (JavaScriptCore) · **bun 1.3.14**

---

## Title

`RegExp` with the sticky (`y`) flag returns `null` when a greedy leading `.*` must backtrack (match exists at position 0)

## What happens

A sticky regex whose leading `.*` greedily consumes characters that must then be **given back via backtracking** so a later token can match fails to find a match — even though a valid match begins exactly at `lastIndex` (0). The same pattern matches correctly without the `y` flag, and both V8 (Node.js) and deno return the match.

## Minimal reproduction

```js
const re = new RegExp(".*x.*", "y");
console.log(re.exec("zzx"));   // greedy .* eats "zzx", backtracks to "zz" so `x` can match
```

| Engine | Result | Correct? |
|--------|--------|----------|
| Node.js v26.5.0 (V8) | `[ 'zzx', index: 0, ... ]` | ✅ |
| deno 2.9.1 | `[ 'zzx', index: 0, ... ]` | ✅ |
| **bun 1.3.14 (JSC)** | **`null`** | ❌ |

## Why `null` is wrong

The sticky flag only requires the match to **begin** at `lastIndex` (here 0). A match anchored at 0 provably exists — `.*x.*` matches all of `"zzx"` starting at 0. Node, deno, and **bun itself without the `y` flag** all find it. Per the spec (`RegExp.prototype[@@match]` / `RegExpBuiltinExec`, sticky path), bun must return that match. Returning `null` is a soundness bug in JSC's sticky matcher.

## Scope / isolation

```js
new RegExp(".*x.*", "y").exec("x")    // bun: ["x"]   — MATCHES (no overshoot to back off)
new RegExp(".*x.*", "y").exec("zzx")  // bun: null    — BUG  (greedy .* overshoots, must backtrack)
new RegExp(".*x.*", "").exec("zzx")   // bun: ["zzx"] — correct without `y`
new RegExp(".+x", "y").exec("x")      // bun: null    — correct (genuinely no match, all engines agree)
```

- Requires the **sticky (`y`) flag**. Non-sticky is correct.
- Requires the leading `.*` to **consume characters and then backtrack**. When `.*` only ever matches the target directly (`"x"`), bun is correct.
- Independent of `^`/`$` anchors and of the `i`/`m`/`s`/`d` flags (all reproduce).
- **Also corrupts `String.prototype.split`, but only through a non-number `limit`.** Measured
  2026-08-03 — the earlier claim that split diverges "regardless of the caller's flags" is wrong;
  plain `"zzx".split(/.*x.*/)` agrees in all three engines, as do all *numeric* limits:

  ```js
  "zzx".split(/.*x.*/, 2)    // node/deno ["",""]   bun ["",""]     ok
  "zzx".split(/.*x.*/, "2")  // node/deno ["",""]   bun ["zz",""]   WRONG
  ```

  `ToUint32("2")` is 2, so those two calls must agree. It is not string-specific either — `"02"`,
  `" 2"`, `"2.0"`, `"2e0"` and even `{valueOf: () => 2}` all reproduce it, so the trigger is
  "limit is not already a number". A plain (non-regexp) separator with a string limit is correct,
  and so is `/.*?x/` (lazy, no backtrack at position 0), which points at bun taking a general
  `split` path for a coercible limit and that path routing through the broken sticky matcher.
  This is how the bug reaches callers that never write `y`.

## Environment

- **Also reproduces on `bun 1.4.0-canary.1+52af83272`** — the Rust rewrite of Bun (merged May 2026,
  canary channel, Linux x64). Behaviour is **byte-for-byte identical to 1.3.14** across the whole
  probe set, which is expected: the rewrite replaced Bun's own runtime code, not JavaScriptCore.
  That is positive evidence the defect lives in **JSC/Yarr**, not in Bun's Zig/Rust layer — i.e. an
  argument for filing at WebKit.
- bun 1.3.14 (buggy) — this is also `bun:latest` (verified 2026-07-24). Compared against Node.js v26.5.0 and deno 2.9.4 (both correct).
- Surfaced by a differential regex-engine fuzzer across node/bun/deno; reduced to the minimal case above.

---

### Filing checklist (internal — remove before posting)

- [x] Re-run the minimal repro against the **latest** bun release — `bun:latest` is 1.3.14; still returns `null` (2026-07-24).
- [ ] Search oven-sh/bun issues for existing sticky/`lastIndex`/JSC-backtracking reports before opening.
- [x] `split` corollary characterised (2026-08-03): trigger is a **non-number `limit`**, not
      "split is always sticky". Worth including — it is how the bug hits non-`y` callers.
- [x] All **seven** corpus witnesses (VC-01…VC-07) verified directly, not by shape (2026-08-03).
- [x] **Not** a JIT bug — identical failures under `BUN_JSC_useRegExpJIT=0`, unlike the
      `v`-mode class and dotAll-offset findings, which vanish with the JIT off.
- [ ] Cross-link the related bun findings if filed together (F003 ignorecase-property-escape, F004 backtracking step-limit) — all JavaScriptCore.
