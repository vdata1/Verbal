# Verbal test surface — APIs, flags, batteries, oracles

Current-state inventory of everything the pipeline actually exercises, written for someone
deciding **where to extend it**. Read off the source, not from memory: `api_descriptors.py`
(APIs, oracles, batteries, serialization), `config/fullcorpus.yaml` (flags, chaos, thresholds),
`regex_facts.py` / `config.py` (flag rules), and the four oracle drivers.

`analysis/EXPERIMENT_GAPS.md` has the long-form history of how this surface was arrived at,
including rationale for choices that look arbitrary here. Its "Expansion surface" section
predates the last two rounds of landings — this document is the current state; that one is the
argument. Where they disagree, this one is right.

---

## 1. Oracles — five, and what each can decide

The oracles are ordered by what they can *settle*, which is not the same as how much they find.

### 1.1 Cross-engine differential — the primary oracle

Run the same harness on node / bun / deno, compare the canonical result. Two engines returning
different bytes for `value` is a discrepancy.

- **Comparable outcome** = `{"ok": true, "value": ...}` or `{"ok": false, "error": <name>}`. A
  thrown regex error is a *comparable outcome*, not a skip — engines disagreeing about whether a
  pattern throws is a finding.
- `exec_ms` is deliberately excluded, so timing can never fake a value discrepancy.
- **Structural ceiling, stated plainly.** It cannot adjudicate: node and deno are both V8, so
  "2 of 3 agree" is one implementation agreeing with itself. And it is *incapable by
  construction* of finding a bug all three engines share. Everything below exists because of
  those two limits.

### 1.2 Tier differential (`tier_diff.py`) — one engine against itself

Run one engine at two optimization tiers. If an engine's JIT and its own interpreter disagree,
**exactly one of them is wrong, by construction** — no majority, no spec argument, no reference
implementation.

| Base | Variant | How |
|---|---|---|
| node | `node_interp` | `node --regexp-interpret-all` |
| deno | `deno_interp` | `deno run --quiet --v8-flags=--regexp-interpret-all` |
| bun | `bun_nojit` | `BUN_JSC_useRegExpJIT=0` (JSC: env var, no argv equivalent) |

Each variant is registered as a **pseudo-engine** in the runner's own `ENGINE_CMD` / `ENGINE_ENV`
tables, so `run_engine`, `_comparable`, timeout and defect classification all apply unchanged.
This is the intended extension point for any new target.

It both finds and **localizes**: three of the bun findings vanish under `useRegExpJIT=0`, placing
them in the Yarr JIT; others reproduce under both tiers, placing them elsewhere. Note a tier that
*times out* is not a disagreement — the interpreter is legitimately slower (measured 59× on bun),
so `tier_timeout` is reported as its own kind, separate from `tier_value_disagreement` and
`tier_defect`.

### 1.3 Metamorphic laws (`laws.py`) — within one engine

A law is a statement that must hold inside a single engine whatever it thinks about anything
else. An engine that breaks one has a bug, full stop. This is the only oracle here that can catch
a bug **every** engine shares.

| Law | Statement | Applicability guard |
|---|---|---|
| `replace_identity` | `s.replace(re, "$&") === s` | always |
| `test_iff_exec` | `re.test(s)` ⟺ `re.exec(s) !== null` | always |
| `search_is_first_index` | `s.search(re)` === first match index, else −1 | not sticky (exec anchors at `lastIndex`, search scans) |
| `lastindex_at_match_end` | `lastIndex` lands exactly at match end | `g` or `y` |
| `indices_address_match` | every `d` span actually addresses its matched text | `d` |
| `matchall_monotonic` | `matchAll` indices strictly increase | `g` |
| `match_is_exec` | `s.match(re)` without `g` deep-equals `re.exec(s)` | not `g` |
| `sticky_anchored_slice` | sticky at `lastIndex k` === `^`-anchored match on `s.slice(k)` | no `m` flag — **heuristic** |

An unsound law is worse than no law: it fires on every engine on every input and buries the real
signal. So each guard is justified at its definition, and the one conditionally-sound law is
marked heuristic in `HEURISTIC_LAWS` rather than quietly trusted. A throw is not a violation —
constructing the regex may legitimately fail.

### 1.4 ReDoS / timing

`exec_ms` is `performance.now()` around the oracle body only, excluding process spawn (node 30ms,
bun 14ms, deno 20ms — engine-correlated, and fatal to a differential timing oracle) and
`new RegExp` compilation.

A case is a **candidate** if `exec_ms > redos_slow_ms` (1000) on any engine **or** any engine hit
the harness timeout. The second trigger is the load-bearing one: the envelope prints only *after*
the call returns, so an engine still backtracking when killed reports no `exec_ms` at all.
Measured on `/(a+)+$/` vs 31 `a`s + `!`: node and deno run for minutes and are killed, bun
returns in 686ms — timing alone sees only bun's number, *under* threshold, and calls it fine.

Candidates are nominated under pool load and confirmed serially on a quiet box (`--redos-defer`
→ `confirm_redos.py`). `engine_specific` is set at slowest/fastest ≥ `redos_engine_ratio` (10×).

**What the shipped artifact does not prove.** Nothing in `redos_<window>.json` demonstrates
ReDoS. Catastrophic backtracking means runtime growing superlinearly *in input length*, and the
in-pipeline tracker never varies length — it times whatever strings generation happened to
produce. What it confirms is engine-specific *slowness*. Growth is a separate oracle: §1.5.

### 1.5 Growth-curve classification (`redos_nomination/`) — built, not integrated

Complexity class of one regex in one engine, from a derived **length family**. Single-engine, so
like the laws it needs no cross-engine vote; unlike everything else here it answers "how does
this scale", not "what does this return".

Per regex: take the recorded fuzz strings → mutate with the real `pipeline.chaos` → keep the
**non-matching** mutants (a matching input never backtracks, so a matching seed can only ever
produce a flat curve — this is what makes chaos load-bearing) → seed = longest non-matcher →
ladder = middle-deletion rungs, which preserves both ends so whatever prefix/suffix forces the
failure survives while the middle shrinks → sweep from tiny `n`, fit `log t ~ n` (exponential)
against `log t ~ log n` (polynomial), classify.

The whole thing stays in the cheap regime — no input costs more than a few ms — because 2ⁿ
explodes so fast that the measurable band is always at small `n`. No pump identification, no
grammar work.

- **Method validated** (`micro_probe.py`): recovers base 2.00 on `/(a+)+$/`, φ=1.618 on
  `/(a|aa)+$/`, k≈2 on `/a+b/`.
- **Run at scale**: all 3,761 `test` regexes of window 6000–9999, node, ~13 min →
  SAFE 3330 · POLYNOMIAL 49 · UNCLASSIFIED 140 · EXPONENTIAL 3 · LINEAR 2 · HANG 1. The three
  exponentials are real (fitted poly degree k = 10.5 / 17.4 / 19.9); an earlier pair of
  exponentials were false positives and are now correctly demoted. Validated 9/9 against
  captured curves.
- **Two bounding lessons, both load-bearing.** The match oracle is Python `re`, itself a
  backtracking engine, so a pathological non-matching mutant blows up *in-process* where the
  sweep's subprocess timeout cannot reach — unbounded, it wedged a core for 3 hours. SIGALRM
  turns that wedge into signal: a timed-out mutant is a proven pathological non-matcher and goes
  to the front of the seed queue. One level down, `re.test()` in JS is synchronous and
  uninterruptible in-thread, so rung timing runs in a worker with the main thread as watchdog →
  `HANG` verdict.

**Why it is listed apart from §1.4.** It is a prototype under `analysis/redos_nomination/`, not
part of the pipeline: it mirrors the chaos config rather than reading it, stands in Python `re`
for the pipeline's own oracle, and its verdicts never reach `redos_<window>.json` — that
artifact carries `serial_ms`/`ratio`/`engine_specific` and no growth fields at all. Corpus
coverage is one window, node only (deno still takes the legacy unbounded path). Integrating it is
§6.3.

### 1.6 Support tooling (not oracles)

`py_re_matches` in each string record is Python `re`'s opinion on whether the string matches — a
generation-quality signal, not a correctness oracle (`null` means unmeasured, never 0).
`dedupe_headline.py` clusters cells into root causes; `reduce.py` minimizes a finding to
`(api, pattern, flags, input)` and is what actually decides two witnesses are the same bug.

---

## 2. APIs — eight, one `ApiDescriptor` row each

The core never branches on `descriptor.api`. **Adding an API is adding a row**, not writing code.

| API | Required flags | min matches | filler | groups must participate | Oracle shape |
|---|---|---|---|---|---|
| `exec` | — | 1 | no | yes | match object; lastIndex battery under `g`/`y` |
| `test` | — | 1 | no | no | boolean; battery (same `RegExpExec` path) |
| `matchAll` | `g` | 2 | yes | no | array of match objects; always batteried (it clones the regex, and the clone inherits `lastIndex`) |
| `match` | — | 1 | no | yes | **dual shape**: match object without `g`, flat string array with `g`; batteried |
| `search` | — | 1 | no | no | index or −1; batteried (`Symbol.search` must save/restore `lastIndex`) |
| `replace` | — | 1 | no | no | `{token → string}` over the 12-token battery + `__fn__` function replacer |
| `replaceAll` | — | 2 | yes | no | same token battery; **throws TypeError unless global** — which is why `required_flags` is empty, so non-`g` variants exercise the throw |
| `split` | — | 1 | no | no | `{default, limit_<L>…}` over the 10-limit battery |

`min_matches` / `filler_between` / `groups_must_participate` are Stage-2 specialization knobs: they
shape the Fandango grammar so generated strings are *interesting* for that API (e.g. `matchAll`
and `replaceAll` need ≥2 matches with filler between for "all" to mean anything).

---

## 3. Flags

**Effective flags for a harness = (API-required ∪ regex-required) ∪ one variant.** The
required-only base is always tested.

- `flag_variants` (config): `["", "i", "m", "s", "y", "d", "g", "v"]`
- Valid alphabet: `d g i m s u v y`. `regex_required` can only ever be `u`.
- **`v` supersedes `u`** rather than unioning — `uv` is a SyntaxError everywhere, and `u` is
  required exactly on the `\p{...}` patterns `v` is interesting on. Unioning would have handed
  every property-escape regex a guaranteed throw and *read as coverage*. Superseding is sound:
  unicodeSets is a strict superset of unicode mode.
- The union **dedups**, so per-API counts differ: `matchAll` (requires `g`) yields 7 variants
  (`g, gi, gm, gs, gy, dg, gv`) because `""` and `"g"` collapse; every other API yields 8.

Always read the effective list from the artifact's `flag_variants`, never from the config —
older artifacts predate `v` and legitimately have fewer.

What each buys: `y`/`g` drive the lastIndex battery and statefulness; `d` adds `.indices` spans,
catching engines that return the same matched *string* from a different *span*; `v` is the newest
and least-settled surface (set difference `--`, intersection `&&`, `\q{…}`, properties-of-strings)
and immediately reproduced a known bun finding on its first run.

---

## 4. Batteries — the hidden multipliers

Fixed and uniform for every regex. Tokens/limits that don't apply to a given regex still run;
engines must agree on those too.

**Replacement tokens (12)** — ``[$&]`` ``[$`]`` ``[$']`` ``[$$]`` ``[$1]`` ``[$<name>]``
``[$12]`` ``[$0]`` ``[$99]`` ``[$<nosuchname>]`` ``[$<>]`` ``[$]``, plus `__fn__`, a function
replacer that JSON-stringifies its
arguments. The last six are the ambiguous ones, which is where engines differ: `$12` with fewer
than 2 groups (`$1` then `"2"`, or group 12?), `$0` (not special), `$99` (no such group),
`$<nosuchname>` (empty vs literal), `$<>` (empty name), dangling `$` (literal).

**Split limits (10 + default)** — `undefined, 0, 1, 1000000, -1, 2**32, 2**32-1, 1.5, NaN, "2"`.
Everything past `1000000` exercises `ToUint32` coercion, a classic bug farm: `-1` → 4294967295
(unlimited), `2**32` → 0 (returns `[]`), `1.5` → 1, `NaN` → 0, `"2"` → 2.

**lastIndex presets (5)** — `[0, 1, floor(len/2), len, len+1]`, deduped. Applied to the five
read-only APIs (`exec`, `test`, `matchAll`, `match`, `search`) only when the regex carries `g`/`y`;
a non-stateful regex bypasses the battery entirely, so its `value` is byte-identical to
pre-battery artifacts. `replace`/`replaceAll`/`split` stay out: they own their own batteries,
which presets would cross-multiply for no additional law.

The battery records both the result **and** the `lastIndex` the call left behind. That second half
is the point — it is the only way to observe `Symbol.search`'s save-and-restore and
`Symbol.match`+`g`'s reset-to-0, laws no cross-engine value comparison can reach.

> One knock-on when reading ReDoS numbers: `exec_ms` brackets the whole oracle body, so a
> *stateful* variant of a batteried API sums **five** calls, making `redos_slow_ms` ~5× easier to
> cross on ~25% of `(api, flags)` combos. Not a regression — `replace` has always summed 13 calls
> and `split` 11 — but it inflates candidate counts without any engine getting slower. The
> engine-specific *ratio* is unaffected, and that is the signal acted on.

---

## 5. Inputs, serialization, targets

**Input generation.** Per (regex, API): a Fandango grammar specialized by the descriptor knobs,
fuzzed for `fuzz_n: 20` solutions (200 generations, 30s budget). Each string is then perturbed
`chaos_n: 2` times — ops `delete, insert, substitute, duplicate, transpose, case_flip, truncate`
over alphabet `a Z 0 <space> \n é 𐐷` (astral + lone-surrogate territory on purpose). Chaos exists
to reach the boundary/negative inputs a matching-strings grammar cannot produce, and it is what
supplies non-matching strings — which is what forces full backtracking search.

**Serialization contract.** One canonical JSON line per harness. `enc` maps `undefined` to an
explicit `{"__undef__": true}` sentinel, because `JSON.stringify` silently drops it in objects and
coerces to `null` in arrays — without that, byte-equality of `value` would be unsound. Named
groups are key-sorted. `.indices` is emitted only under `d`, so the axis is purely additive.

**Targets.** node v26.5.0 (V8), bun 1.3.14 (JSC/Yarr), deno 2.9.1 (V8). Plus an optional
**bun canary** (the 2026 Rust rewrite): all five findings reproduce on it byte-for-byte
identically, and the tier differential holds there too — which is evidence the defects live in
JSC/Yarr rather than Bun's own runtime layer. It is deliberately not wired into `ENGINE_CMD`,
since a fourth engine would change provenance for every recorded artifact.

**Scale per regex**: 8 APIs × 60 strings × 7–8 flag variants ≈ **3,780 harnesses**, one `.js` file
each.

---

## 6. Open surface — where extension is actually worth it

Ordered by what it would *settle*, not by effort.

1. **A spec-faithful reference implementation** (e.g. engine262) as a target. This is the one that
   changes the epistemics: it turns a *vote* into a *verdict*, fixing the V8-twins problem at the
   root. Adding more independent engines (JSC standalone, SpiderMonkey, QuickJS, Hermes) improves
   the vote; a reference ends it.
2. **UCD ground truth for `\p{...}`.** Compare property membership against the Unicode Character
   Database directly. Would have turned the deno property-table finding from "engines disagree"
   into "deno is wrong" with no era-ladder probe — and, unlike any differential test, catches a
   property *all three* engines get wrong.
3. **Integrate growth-curve classification into the pipeline.** The method is *done* (§1.5) —
   validated, run over a full window, three real exponentials found. What is missing is
   plumbing, not insight: it lives in `analysis/redos_nomination/` as a prototype, mirrors the
   chaos config instead of reading it, substitutes Python `re` for the pipeline's own
   `py_re_matches` oracle, runs under no provenance, and emits nothing into
   `redos_<window>.json`. Integration means reusing the transpiler's oracle, running under the
   pool's provenance, extending the ReDoS artifact with the fitted class, and giving deno the
   bounded worker path node and bun already have. Two honest caveats to carry across: every
   POLYNOMIAL/UNCLASSIFIED nomination peaks sub-10µs, so at nominate time they are
   indistinguishable from fit noise (a confirm-phase question — run a longer input — not a
   classify one), and coverage so far is one window on one engine.
4. **Multi-call statefulness.** Single-call `lastIndex` is observed via the preset battery; a
   *looped* `exec` — call until null, checking the sequence of matches and lastIndex values — is
   not. Classic divergence area, and the last item outstanding from the original expansion list.
5. **More laws.** The mechanism is proven and each law is ~10 lines. Untried: adding `d` must not
   change `match`/`index`; a redundant `(?:)` must not change the result; `matchAll[0]` ≈
   `exec` under `g`.
6. **ReDoS nomination is starvation-sensitive** (G9): a sound static pre-filter would cut the
   confirm queue for free.
7. **Case-mapping APIs are out of scope** (G5), so a real `i`-flag case-folding skew is currently
   unreachable.
8. **Lower priority**: invoking `RegExp.prototype[Symbol.replace/split/match/search]` directly
   (tests the protocol rather than the String wrapper), and `RegExp.prototype.compile` (legacy
   in-place mutation).

### Where each kind of change goes

| To add | Edit | Cost |
|---|---|---|
| a flag | `flag_variants` in the run config | one line |
| a battery value | `_REPLACE_TOKENS` / `_SPLIT_LIMITS_JS` / `_LASTINDEX_PRESETS_JS` | one list entry |
| an API | one `ApiDescriptor` row + its oracle snippet | data, not core code |
| an engine or tier | `ENGINE_CMD` / `ENGINE_ENV` (pseudo-engine registration) | one dict entry |
| an oracle | a new driver over the harnesses already on disk | standalone script |

The last row is why the oracle axis is cheap: `tier_diff.py` and `laws.py` both run over existing
artifacts and need no regeneration. A new oracle costs a script, not a corpus sweep.
