# Bug report (draft, ready to file) — deno (F001): regexp `\p{...}` tables lag behind the reported Unicode version

**Target:** [denoland/deno](https://github.com/denoland/deno/issues) · **Component:** V8 regexp Unicode property data · **deno 2.9.4** (= `deno:latest`)

---

## Title

`\p{L}` (and the whole property table) misses Unicode 17.0 code points, while `deno --version` / `process.versions.unicode` report Unicode 17.0

## What happens

Under the `u` flag, deno classifies code points **added in Unicode 17.0** as non-letters — its regexp property tables behave as Unicode 16.0. The inconsistency that makes this a clear bug: deno **self-reports Unicode 17.0**, so the runtime claims data it does not deliver.

## Minimal reproduction

```js
new RegExp("[\\p{L}0-9]", "u").test(String.fromCodePoint(0x32D50));  // U+32D50, CJK Ext J (Unicode 17.0)
```

| Engine | Result | Correct? |
|--------|--------|----------|
| Node.js v26.5.0 | `true` | ✅ |
| bun 1.3.14 | `true` | ✅ |
| **deno 2.9.4** | **`false`** | ❌ |

Reproduces across the whole 17.0 range, e.g. `\u{323B0}` (CJK Ext J), `\u{16EAC}` (Beria Erfe), `\u{18DEF}` — every one is a letter node/bun match and deno drops.

## It is a clean 16.0 → 17.0 cutoff

Era ladder for `/\p{L}/u` on the pinned engines — deno is correct through 16.0 and misses only 17.0 additions:

| representative code point | Unicode era | node | bun | deno |
|---------------------------|-------------|:----:|:---:|:----:|
| U+105C0 Todhri | 16.0 | ✓ | ✓ | ✓ |
| U+16D40 Kirat Rai | 16.0 | ✓ | ✓ | ✓ |
| U+323B0 CJK Ext J | **17.0** | ✓ | ✓ | **✗** |
| U+16EAC Beria Erfe | **17.0** | ✓ | ✓ | **✗** |

Not over-matching: all three engines answer `\p{L}` = `false` for code points **unassigned** in 17.0 (including ones placed immediately past each new block), so deno carries real 16.0 data, not plane-range approximations. The lag is table-wide, not `\p{L}`-only: deno also returns `/\p{Script=Han}/u` = `false` for U+323B0.

## Why this is deno's bug and not "just old data"

The sharp part is the **self-report inconsistency** — the version strings must not be used to explain the split, because they mislead:

| runtime | self-reports | regexp tables (`\p{Lu}`) |
|---------|--------------|--------------------------|
| node | unicode 17.0 / icu 78.3 | 17.0 ✅ |
| **deno** | **unicode 17.0 / icu 78.3** | **16.0 ❌** |
| bun | unicode 15.1 / icu 75.1 | 17.0 ✅ |

deno reports the **same** Unicode/ICU numbers as node while its regexp property tables behave a full major version behind. deno's V8 is actually *newer* than node's (V8 14.9.207 vs 14.6.202), so this is about the bundled property **data**, independent of the JS-engine version. The ask: either ship the 17.0 regexp tables to match the reported version, or correct what the runtime reports.

## Environment

- deno 2.9.4 (buggy; = `deno:latest`, re-verified 2026-07-24 — **still fails**, unchanged from 2.9.1), vs Node.js v26.5.0 and bun 1.3.14 (both correct).
- Surfaced by a differential regex fuzzer (node/bun/deno) on the `u`-flag dimension.

---

### Filing checklist (internal — remove before posting)

- [x] Re-verified on `deno:latest` (2.9.4) — still `false` (2026-07-24); not fixed since 2.9.1.
- [ ] This may be an upstream V8 ICU-data issue rather than deno-specific — check whether node's newer-still bundling differs, and whether to file at deno or V8. The self-report inconsistency is deno's to answer regardless.
- [ ] Confirm the exact Unicode version that assigned U+18DEF to tighten "16.0-era" to an exact cutoff.
- [ ] Local evidence: `analysis/differential_findings/regex_8576_9921__unicode17_witnesses/` (probe.js + probe_output.txt, era ladder + self-report tables).
