# Bug report (draft, ready to file) — bun (F003): `\p{...}` property escapes are not case-folded under `/i`

**Target:** [oven-sh/bun](https://github.com/oven-sh/bun/issues) · **Component:** RegExp (JavaScriptCore / Yarr) · **bun 1.3.14** (= `bun:latest`)

---

## Title

`RegExp` with `/iu` (or `/vi`) does not apply case folding to Unicode property escapes `\p{...}`

## What happens

Under the `i` (ignoreCase) flag, bun applies case folding to literal character ranges but **not** to Unicode property escapes. A property set like `\p{Uppercase_Letter}` fails to match a lowercase character whose uppercase form is in the set, even though the spec requires the fold.

## Minimal reproduction

```js
new RegExp("\\p{Uppercase_Letter}", "iu").test("ც");  // "ც" GEORGIAN LETTER CAN
```

| Engine | Result | Correct? |
|--------|--------|----------|
| Node.js v26.5.0 | `true` | ✅ |
| deno 2.9.4 | `true` | ✅ |
| **bun 1.3.14** | **`false`** | ❌ |

`ც` (U+10EA) folds to itself; its Mtavruli capital `Ც` (U+1CAA) is `General_Category=Lu`, hence in `\p{Uppercase_Letter}`. Under `/i` the set must match `ც`.

## Why `false` is wrong (spec-backed)

ES2024 §22.2.2.7.1 `CharacterSetMatcher`: under `/iu`, the input is canonicalized to `cc` and the set matches iff **some** member `a` of the set has `Canonicalize(a) === cc`. `scf("ც") = "ც"`, `"Ც"` ∈ `\p{Uppercase_Letter}`, `scf("Ც") = "ც"` — so it must match. Node and deno both do.

## The decisive evidence: bun contradicts itself

bun folds literal ranges but not property escapes — the same `/i` applied two ways, inconsistently. From a spec-derived probe (bun scores **5/11** where node and deno each score **11/11**):

```js
/\p{Lu}/iu.test("a")                 // want true — bun: false  ✗
/\p{Ll}/iu.test("A")                 // want true — bun: false  ✗
/\p{Lu}/iu.test("é")                 // want true — bun: false  ✗
/\p{Uppercase_Letter}/iu.test("a")   // want true — bun: false  ✗
/[\p{Lu}]/iu.test("a")               // want true — bun: false  ✗ (inside a class)
/\p{Lu}/vi.test("a")                 // want true — bun: false  ✗ (v flag too)
/\p{Lu}/iu.test("A")                 // want true — bun: true   ✓
/\p{Lu}/u.test("a")                  // want false — bun: false ✓ (control, no i)
/[A-Z]/iu.test("a")                  // want true — bun: TRUE   ✓ (range folding works!)
/[a-z]/iu.test("A")                  // want true — bun: TRUE   ✓ (range folding works!)
```

The last two rows are the argument: **bun folds literal ranges correctly and property escapes not at all.** The `/u`-only controls pass, so the property set itself is correct — only the folding step is missing. Reproduces under `u` and `v`, inside and outside character classes, ASCII and non-ASCII.

## Suspected root cause (from outside)

Consistent with JSC's Yarr building property-escape sets without routing them through the same canonicalization path it applies to ranges.

## Environment

- bun 1.3.14 (buggy; = `bun:latest`, re-verified 2026-07-24), vs Node.js v26.5.0 and deno 2.9.4 (both correct).
- Surfaced by a differential regex fuzzer (node/bun/deno) with case-flip mutation; reduced to the case above.

---

### Filing checklist (internal — remove before posting)

- [x] Re-verified on `bun:latest` (1.3.14) — still `false` (2026-07-24).
- [ ] Search oven-sh/bun issues for existing `\p{...}` / ignoreCase / Yarr case-folding reports.
- [ ] Consider filing together with the sticky-`.*` and backtracking-cap bugs (all JavaScriptCore) and cross-linking.
- [ ] Local evidence: `analysis/differential_findings/regex_9921__bun_ignorecase_property_escape/` (probe + full output).
