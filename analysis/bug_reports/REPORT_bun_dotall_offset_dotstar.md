# Bug report (draft) — bun (Bug F): the `s` flag changes where a match starts when `lastIndex` > 0

**Target:** [oven-sh/bun](https://github.com/oven-sh/bun/issues) · **Component:** RegExp (JavaScriptCore / Yarr JIT) · **bun 1.3.14** (= `bun:latest`)

> ⚠️ **Correctness:** with `lastIndex` set past 0, bun matches from index **0** anyway — it returns
> a match that begins *before* the search start it was given. The wrong `index` and the wrong
> matched substring propagate into `matchAll`.

---

## Title

With `lastIndex` > 0, a `/.*X.*/gs` match starts at index 0 instead of at `lastIndex` — and the
`s` flag alone flips the result even when it cannot affect the language

## Minimal reproduction

```js
const re = /.*X.*/gs;
re.lastIndex = 1;
re.exec("aaXb");
```

| Engine | Result |
|---|---|
| Node.js v26.5.0 | `"aXb"` at index **1** ✅ |
| deno 2.9.1 | `"aXb"` at index **1** ✅ |
| **bun 1.3.14** | `"aaXb"` at index **0** ❌ — begins *before* `lastIndex` |

Drop the `s` and bun is correct: `/.*X.*/g` with `lastIndex = 1` gives `"aXb"` at 1 in all three
engines. **The subject `"aaXb"` contains no line terminator**, so `s` — which only controls
whether `.` matches line terminators — cannot legally change anything here.

## The `s` flag is provably a no-op in this repro, and still changes the answer

The sharpest form uses a pattern where `s` is a no-op *by construction*, not just for this
subject. `[\s\S]` already matches every code point, so `s` cannot alter it:

```js
new RegExp("[\\s\\S]*X[\\s\\S]*", "g" ).exec(...)   // lastIndex 1 -> @1 "aXb"   bun ✅
new RegExp("[\\s\\S]*X[\\s\\S]*", "gs").exec(...)   // lastIndex 1 -> @0 "aaXb"  bun ❌
```

Same pattern, same subject, same semantics — only the flag differs, and the answer changes. There
is no reading of the spec under which those two calls may differ. This is the single most useful
line to hand a maintainer.

## Disabling the RegExp JIT fixes it

`BUN_JSC_useRegExpJIT=0` makes every failing case correct — **6 of 16 wrong with the JIT, 0 of 16
without**, over the probe set below. As with the `v`-mode class bug
([`REPORT_bun_vmode_class_union_atomicity.md`](REPORT_bun_vmode_class_union_atomicity.md)) this
means:

- the defect is in **JIT codegen**, not in parsing or semantics — the interpreter is right;
- **ground truth needs no cross-engine vote**: the same binary disagrees with itself across tiers.

## Trigger

`s` + a nonzero `lastIndex` + a greedy unbounded `.`-quantifier on **both** sides of a literal.
Empirically (all at `lastIndex = 1` on `"aaXb"`, where correct is `@1 "aXb"`):

| Pattern (`/gs`) | bun | |
|---|---|---|
| `.*X.*` | **@0** ❌ | the corpus shape |
| `.*X.+` | **@0** ❌ | |
| `.*X.{0,}` | **@0** ❌ | |
| `[\s\S]*X[\s\S]*` | **@0** ❌ | `s` is a no-op here — see above |
| `.*X` | @1 ✅ | no trailing quantifier |
| `.*X.` / `.*X.?` | @1 ✅ | trailing quantifier must be unbounded |
| `.*X[^]*` | @1 ✅ | |
| `.*X.*?` / `.*?X.*?` | @1 ✅ | lazy is fine |
| `.+X.*` | @1 ✅ | leading `.+` is fine |
| `[^]*X.*` | @1 ✅ | |
| `X.*` | @2 ✅ | no leading quantifier |
| `^.*X` | NULL ✅ | anchored, all engines agree |

Every `lastIndex` > 0 collapses to the same wrong answer — `@0` for `lastIndex` 1, 2 and 3 alike;
it does not merely lose one position, it discards the offset entirely.

Do not read this table as a semantic rule. Since the interpreter handles every row correctly, the
pattern shape is selecting *which compiled path runs*, and only some of those are miscompiled —
the boundary looks arbitrary because a miscompile's boundary is arbitrary.

## Blast radius

- **`exec`** — wrong `index` and wrong matched substring.
- **`matchAll`** — the first yielded match is the wrong one (`@0 "aaXb"` instead of `@1 "aXb"`).
  This is how it reached the corpus, since `matchAll` seeds its clone's `lastIndex` from the
  source regexp.
- **`test`** returns `true` in both engines here, and the post-match `lastIndex` is 4 either way,
  so neither surfaces the divergence. The damage is confined to *where* the match is reported,
  not *whether* one exists.

## Corpus incidence — this fully explains a 170-case residue

Found by a differential fuzzing pipeline over a 537k-regex corpus, window 12050–15050. Three
regexes carried an unexplained `matchAll` cluster that the known sticky-`.*` bug did not account
for (`matchAll` builds no sticky matcher):

| regex_id | pattern | `gs` discrepancies |
|---|---|---:|
| `regex_14057` | `.*RUNTIME DEBUG.*` | 58 |
| `regex_14862` | `.*Unfortunately the server does not support such operation.*` | 58 |
| `regex_13552` | `.*"Red Hat Enterprise Linux for Virtual Datacenters, Premium",1,RH00001.*` | 54 |
| | | **170** |

That is exactly the ~170-case residue, and every one of them is flag `gs`. All three patterns are
the `.*<literal>.*` shape this bug requires.

**These are not the sticky bug.** The three regexes also produce sticky (`gy`) discrepancies,
which *are* [`REPORT_bun_sticky_dotstar.md`](REPORT_bun_sticky_dotstar.md) — but that bug
reproduces with the JIT disabled and this one does not, so they are separate defects that happen
to share a pattern shape. Do not merge them.

## Environment

- **Also reproduces on `bun 1.4.0-canary.1+52af83272`** — the Rust rewrite of Bun (merged May 2026,
  canary channel, Linux x64). Behaviour is **byte-for-byte identical to 1.3.14** across the whole
  probe set, which is expected: the rewrite replaced Bun's own runtime code, not JavaScriptCore.
  That is positive evidence the defect lives in **JSC/Yarr**, not in Bun's Zig/Rust layer — i.e. an
  argument for filing at WebKit.
- **bun 1.3.14** (buggy; = `bun:latest`), vs **Node.js v26.5.0** and **deno 2.9.1**, which agree
  with each other on every case probed.
- Verified 2026-08-03 in a pinned container, all three engines in one invocation.
- Probes: `/scratch/turcotte/verbal/probes_2026-08-03/probe_dotstar_{offset,dotall,final}.js`,
  `probe_matchall_lastindex.js`

---

### Filing checklist (internal — remove before posting)

- [x] Minimal repro reduced to three lines, verified on all three engines (2026-08-03).
- [x] **`s`-is-a-no-op demonstration** (`[\s\S]*X[\s\S]*` under `g` vs `gs`) — lead with this.
- [x] Localized to the Yarr JIT (6/16 wrong with, 0/16 without).
- [x] Trigger boundary mapped; separated from the sticky-`.*` bug by the JIT test.
- [x] Accounts for the full 170-case corpus residue.
- [ ] Search oven-sh/bun and WebKit Bugzilla for existing dotAll / `lastIndex` / Yarr JIT reports.
- [ ] Venue: likely **WebKit (Yarr)** rather than bun, same as the `v`-mode class bug — check
      whether bun carries JSC patches here first.
- [ ] Consider filing together with the `v`-mode class bug: both are Yarr JIT miscompiles found
      the same day, and a maintainer may want them as one investigation.
