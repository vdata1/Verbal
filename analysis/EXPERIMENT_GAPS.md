# Experiment gaps — what the pipeline cannot currently see

**Prepared:** 2026-07-15, after the 6000–9999 differential eval
(`results-run-6000-9999/eval_headline_6000_10000.json`: 3,767 regexes, 1,008,012
cases, 44 value discrepancies, 0 defects, provenance `8dc8b1d`).

**Updated 2026-07-15 (`d1f3125`): G7 is fixed and G3 is mostly fixed.** Every
number describing the 6000–9999 window still stands — that window was generated
without chaos and is unchanged. What changed is the pipeline: `pipeline.chaos` now
perturbs each generated string into boundary inputs, and the first thing it did was
find a bug this document had listed as invisible
([F003](differential_findings/DISCREPANCIES.md#f003)). See [G7](#g7) and
[G3b](#g3) for the measured before/after.

Every number below is measured on that window and reproducible from its artifacts.
This is about **the experiment**, not the engines: each gap is a way a real
cross-engine difference can exist and not appear in a headline. They are ordered by
how much signal they cost.

| # | Gap | Cost in the 6000–9999 window | Status |
|---|-----|------------------------------|--------|
| [G1](#g1) | Validity gate tests different flags than the harness runs | **7 of 13** `\p{...}` regexes never compiled; recorded `ok` | **fixed** (2026-07-21) |
| [G2](#g2) | `status: ok` can mean "generated nothing" | 6 regexes, **3 of them** `\p{...}` | **fixed** (2026-07-21) |
| [G3](#g3) | Flag variants widen the accepted language; inputs never follow | 2 known bugs under-reported, 1 invisible | **mostly fixed** (`d1f3125`) |
| [G4](#g4) | No orchestration for parallel-window generation + eval | the eval sat un-run for ~14h | **fixed** (2026-07-21) |
| [G5](#g5) | Case-mapping APIs are out of scope, so an ICU/Yarr skew is unreachable | 1 known skew invisible | open (scope call) |
| [G6](#g6) | ~~Artifacts not reproducible from recorded provenance~~ — **the recipe was wrong; they reproduce byte-for-byte** | none; provenance omits chunk context for pre-`3ab1fc3` artifacts | **resolved** (2026-07-15); [leftover item 2 done](#g6-item2-done) (2026-07-30) |
| [G7](#g7) | **We generate only in-language strings; the bugs live outside** | both known bugs under-reported | **fixed** (`d1f3125`) |
| [G8](#g8) | Provenance silently recorded no commit at all | the whole 6000–10050 window (6.9M cases) untraceable | **fixed** (2026-07-30) |
| [G9](#g9) | ReDoS nomination fires on process starvation, not backtracking | **79 of 239** queued rows structurally cannot backtrack; ~152 show the starvation signature | open |

G1–G3 all cost signal in the same place: **`\p{...}` regexes**, which is exactly
where [F001](differential_findings/DISCREPANCIES.md#f001) lives. G7 is the general
principle that G3 is a special case of, and was the single highest-value item here
— which the fix bore out: it converted G3b from a hand-written probe into a
pipeline-surfaced finding (F003) on its first run.

**Update 2026-07-21: G1 and G2 are both fixed.** The validity gate now validates
each pattern under the construction-affecting flags its harness will carry
(`js_construction_flags` → `/u` for a `\p{...}`/`\u{...}` pattern), so a pattern that
`SyntaxError`s under `/u` is classified `not_js` instead of a silent `ok` — the 7
non-compiling `\p{...}` regexes move out of the evaluated set. And a regex that
specialized but generated zero test strings on every API now gets a distinct
`no_inputs` status instead of `ok`, correcting `regexes_evaluated` 3767 → 3761. Both
were validated against the recorded 6000–9999 run: exactly the predicted 7 and 6
regexes flip. See [G1](#g1) and [G2](#g2) for the fix details.

These were the highest-value open items, and G7's fix had raised their price: chaos
makes every executed `\p{...}` regex substantially more likely to flag, so the
10-of-13 that never executed cost more signal than they did when this document was
written — which is why they were closed next.

A separate [expansion surface](#expansion) section lists APIs, parameter values,
flags and oracles we do not yet exercise — that is coverage we have never had, as
opposed to coverage we are losing.

---

## G1 — The JS-validity gate tests the pattern under different flags than the harness runs {#g1}

`src/pipeline/js_regex_probe.js` decides whether a corpus row is a JS regex, and says
why it uses no flags:

> Validity is tested with `new RegExp(pattern)` using NO flags — the flags the
> pipeline's harnesses actually use (g at most) do not affect construction validity;
> **only the `u`/`v` flags change escape strictness, and we do not use them.**

**That last clause is no longer true.** `regex_facts.py` computes `requires_flags`,
and a pattern containing `\p{` requires `u`. So the gate admits a pattern on the
strength of an invariant the specializer then breaks: the gate proves it constructs
*without* `/u`, and the harness runs it *with* `/u`, where escape rules are stricter.

The comment is the bug. Nothing re-checked it when `u` was added.

### Cost

Seven of the 13 `\p{...}` regexes in the window throw `SyntaxError` on **every**
engine, in every case, and are recorded as `status: ok`:

| regex_id | pattern | why it dies under `/u` |
|----------|---------|------------------------|
| `regex_6166` | `[\p{Space}]+` | `\p{Space}` is Perl/POSIX; JS has `\p{White_Space}` |
| `regex_6302` | `…_\p{IsAlpha}+…` | `\p{IsAlpha}` is Perl |
| `regex_6421` | `(?:X\|binary)'(?:\p{XDigit}{2})*'` | `\p{XDigit}` is POSIX |
| `regex_6921` | `[\Â¿\Â¡\p{Lu}l]` | `\Â` is an illegal escape under `/u` |
| `regex_7217` | `\W(\$\p{Alpha}\p{Alnum}*)\b` | `\p{Alpha}`, `\p{Alnum}` are POSIX |
| `regex_9777` | `\p{Print}` | `\p{Print}` is POSIX |
| `regex_9780` | `[\p{L}\d  ]+[\,.:;!?]+…` | `\,` is an illegal escape under `/u` |

All seven construct fine **without** `/u`, where `\p{Space}` is just the literal
characters `p{Space}` — which is precisely why the gate passed them.

`regex_9780` is the one that stings. Its generated inputs contain **48 occurrences of
13 distinct Unicode 17.0 code points** (U+3250A, U+32777, U+32D50, U+333B5, …), every
one of which node calls a letter and deno does not. It is a textbook F001 trigger and
it contributed **zero** cases, because `[\,.:;!?]` is a `SyntaxError` under `/u`.

Window-wide, **exactly 7 regexes** (0.2%) never compile on any engine, and they are
**precisely these 7** — every single non-compiling regex in the window is a `\p{...}`
regex. They account for all 2,688 dead cases (0.3%). No regex fails on only *some*
APIs. So the damage is small in aggregate and perfectly concentrated: 0.2% of the
window, 54% of the population F001 lives in.

### Fix — and a genuine design choice

The current state is indefensible: require `/u`, guarantee a `SyntaxError` on every
engine, record `ok`, report nothing. But there are two defensible repairs, and they
disagree:

1. **Validate under the effective flags.** If the pattern doesn't construct under the
   flags the harness will use, classify `not_js` and exclude it. Honest, and the
   counts stop lying.
2. **Don't require `/u` for a pattern that is invalid under `/u`.** Run it unflagged,
   as the literal-escape regex JS thinks it is. This preserves the gate's stated
   stance — *"even if it is a Perl idiom that JS interprets as literal escapes,
   engines still must agree on it"* — and keeps testing something real.

(2) preserves more corpus and is truer to the gate's design intent; (1) is simpler.
Either way the invariant must be **checked**, not asserted in a comment. Whichever is
chosen, a pattern whose harness cannot compile on any engine must never be `ok`.

### Fixed (2026-07-21) — chose (1): validate under the effective flags

The choice went to (1) over (2) on an honesty argument (2)'s own worked example
undercuts: for the mixed pattern `regex_9780` (`[\p{L}\d ]+[\,.:;!?]+`), the `\p{L}`
is the F001-relevant *letter class* only under `/u`, but the `\,` is illegal under
`/u`, so running it unflagged (2) doesn't recover the F001 signal — it tests a
degenerate all-literal regex and counts that as coverage. (1) makes the count honest
instead: a pattern that can't construct on any engine is `not_js`, excluded.

`regex_facts.js_construction_flags(pattern)` returns the `u`-only slice of
`effective_flags` (the sole construction-gating flag; `\u{...}`/`\p{...}` → `u`), and
`run.process_row_range` passes it per-pattern into `classify_js`, which now validates
`new RegExp(src, flags)` in `js_regex_probe.js`. Verified against the recorded
6000–9999 window: the 7 `\p{...}` regexes flip `ok → not_js`; a well-formed `\p{L}+`
(valid under `/u`) stays in scope; the legacy flagless path is preserved for callers
that don't specialize.

---

## G2 — `status: ok` can mean "generated zero test inputs" {#g2}

Six regexes in the window are recorded `status: ok` with `num_strings: 0` for all
five APIs. They produce no harnesses, evaluate to no cases, and emit no warning. The
headline counts them in `regexes_evaluated: 3767`; the true figure is 3,761.

```
regex_6784   ([\d\s\p{L}:,\.]{3,})+
regex_8033   [\p{L}\p{M}\p{S}\p{N}\p{P}\s*]*\{##…
regex_8084   (?:[^\p{L}\p{N}*]|^)([+\-|]?(?:[\p{L}\p{N}*]+'?)*[\p{L}\p{N}*])…
regex_6917   (<blockquote>\n){50000}
regex_8326   ^(?=((?:[^"']+|"[^"\\]*…
regex_8897   \A ( (?:.*[^\\]|) … )
```

A further 13 generated zero strings for *some* APIs — a partial no-op, equally silent.

The pattern is legible: huge character classes with unbounded repetition. The fuzzer
hits `fuzz_timeout_s: 30` and yields nothing. **Three of the six are `\p{...}`
regexes** — 0.2% of the window overall, 23% of the property-escape population, again
concentrated on F001.

**Fix.** `ok` should mean "we tested it". Add a distinct terminal status
(`no_inputs`) for a regex that generated nothing, surface a count in the headline,
and stop counting them as evaluated. The artifacts already carry `num_strings`, so
this is an accounting change, not new machinery. Raising `fuzz_timeout_s` for
large-class regexes is a separate question and should be decided on its own.

### Fixed (2026-07-21)

`run.process_row_range` now assigns `no_inputs` when a regex specialized but every API
returned `num_strings == 0`, distinct from `ok`. The eval keys off `status == "ok"`,
so these fall out of the evaluated set automatically — `regexes_evaluated` corrects
3767 → 3761, the true figure. Applied to the recorded 6000–9999 run the predicate
flips exactly the 6 regexes named above and nothing else. The partial-no-op case (0
strings on *some* APIs) is left as-is: the per-API `num_strings` already records it,
and a terminal status can't capture a partial. Raising `fuzz_timeout_s` remains a
separate, undecided question.

---

## G3 — Flag variants widen the accepted language; input generation never follows {#g3}

> **Mostly fixed 2026-07-15 (`d1f3125`).** [G7](#g7)'s `chaos` transform is the fix
> for 3a and 3b: `insert@0` gives every API the leading pad only `matchAll` had, and
> `case_flip` supplies the case-varied input `i` variants never had. 3b is now a
> confirmed finding, [F003](differential_findings/DISCREPANCIES.md#f003), surfaced by
> the pipeline itself. 3c is partly addressed — `\n` is in `chaos_alphabet`, so
> `insert`/`substitute` give `m`/`s` variants line structure to act on, but by luck
> rather than by construction. The diagnosis below is kept as written; the fix is
> recorded per-witness.

**The pipeline generates inputs from the base pattern's grammar, then runs those same
inputs under every flag variant.** But a flag variant is not a different way of
running the same test — it is a *different regex*, accepting a different language. The
inputs never move to match. So each variant tests only the sliver of its language that
the base pattern already generated.

Three witnesses, in increasing order of how badly it hides a real bug:

### 3a. `matchAll` pads; the other four APIs don't (known)

`specialize.py:13-14` rewrites `<start>` to `<pad> (<m> <pad>){k,K}` only when
`min_matches > 1` — i.e. only for `matchAll`. Every other API's grammar is bare
`<start> ::= <r0>`, so **the generated string *is* the match and it always begins at
index 0.**

This is why the `regex_5354` bun anchor bug (candidate F002) was seen by 1 of 5
APIs: it needs a match at index > 0, and only `matchAll` ever produces one. Its blast
radius is 5 APIs; the pipeline reported 1. See
`differential_findings/HANDOFF_regex_5354.md`.

**Fixed 2026-07-15 (`d1f3125`):** `chaos`'s `insert` op can prepend (position 0 is a
candidate, and `tests/test_chaos.py::test_insert_can_prepend` pins that it stays
reachable), so every API now gets leading-pad inputs rather than just `matchAll`.
Whether that lifts `regex_5354` from 1 API to 5 is **not yet measured** — it needs a
re-run of that row, which is also what [G6](#g6) wants. Worth doing together.

### 3b. `i` widens the language; inputs are never case-varied (new)

The sharpest case, because the pipeline had **everything it needed and still saw
nothing**.

`/\p{Lu}/iu.test("a")` returns **`false` on bun**, `true` on node and deno. Per spec
(ES2024 §22.2.2.7.1 `CharacterSetMatcher`) `/iu` canonicalizes the input to `cc` and
matches if *there exists* a member `a` of the set with `Canonicalize(a) === cc`;
`scf("a")` is `"a"`, `"A"` is in `\p{Lu}`, `scf("A")` is `"a"` — so it must match.
bun scores 5/11 against a spec-derived probe where node and deno score 11/11. Its
controls are what convict it: `/[A-Z]/iu.test("a")` is `true` on bun, and
`/\p{Lu}/u.test("a")` is correctly `false` — so **bun applies case folding to literal
ranges but not to property escapes**. It contradicts itself; this is not a defensible
reading. Reproduces under `u` and `v`, inside and outside classes, on ASCII.

`regex_9921` is `\p{Uppercase_Letter}`. Its flag variants **already included `giu`** —
the exact regex, the exact flag. It found nothing:

```
pattern      : \p{Uppercase_Letter}
flag_variants: ['gu', 'giu', 'gmu', 'gsu']   <- giu WAS tested
strings containing ANY lowercase letter: 0/20
```

The fuzzer generates strings matching `\p{Uppercase_Letter}`, so they are uppercase.
Under `giu` bun matches uppercase correctly. Exposing the bug needs a **lowercase**
letter — a string the base pattern by construction never generates.

**Resolved 2026-07-15 (`d1f3125`).** This was the sharpest case precisely because the
only missing ingredient was the input, and that is exactly what [G7](#g7)'s `chaos`
supplies. Re-running the same regex on the same engines with chaos as the only
variable:

| | cases | value discrepancies |
|---|------:|--------------------:|
| chaos off (the pipeline as this document found it) | 400 | 4 |
| chaos on (`chaos_n: 2`) | 1,200 | **59** — 4 fuzz + **55 chaos** |

The 4 fuzz discrepancies are byte-identical to the F001 witnesses already recorded
for this regex, which is the control: chaos appended without disturbing the fuzz
population or its `n` ids. All 55 new ones carry `flags=iu`, and the mutation that
produced the clearest is `case_flip@0` — the op named for this gap.
`/\p{Uppercase_Letter}/iu.test("ც")` is `true` on node and deno, **`false` on bun**.

So the prediction in this section held exactly: the pipeline had everything it
needed, and the one thing it lacked was a lowercase letter. The bug is now
[F003](differential_findings/DISCREPANCIES.md#f003), and — unlike when this document
was written — it was surfaced **by the pipeline**, not by a hand-written probe.

### 3c. The general shape

`m` and `s` have the same disease. `m` changes what `^`/`$` mean, but inputs are not
generated with line structure in mind; `s` changes what `.` matches, but inputs
contain a newline only by luck.

**Fix.** Derive inputs **per flag variant**, not per base pattern. Cheapest useful
version, no grammar work:

- for an `i` variant, emit case-flipped copies of each generated string;
- for every API, emit a leading-pad copy (generalizing what `matchAll` already does),
  so a match at index > 0 is always exercised;
- for `m`/`s`, emit a copy with an embedded newline.

That is a post-generation string transform. It would have caught 3a and 3b with the
existing five APIs and no new engine surface.

---

## G4 — No orchestration for parallel-window generation followed by eval {#g4}

`scoped_run.sh` chains generation → adapter → eval in one launch, but its Phase A is
**serial**. At ~40 min per 100-row chunk, 4,000 rows serially is ~26h — past the 12h
budget the 6000–9999 drivers were given. So that run used `overnight_drive.sh`
directly, 8× in parallel with `START=6000…9500` into one shared outdir (~3.4h), and
`overnight_drive.sh` has **no eval phase** — it aggregates and exits.

`scoped_run.sh` also cannot simply be run 8× in parallel: its adapter
(`chunks_to_run_record.py`) globs *all* `chunk_*.json` in the outdir and derives the
window from their min/max index, so concurrent copies would each build a record over
whatever existed at that instant, race on the derived filename, and launch 8
concurrent evals at 24 workers each.

So the eval became a manual step nothing enforced, and it didn't happen — the window
finished generating at 20:30 UTC on 2026-07-14 and the eval was launched by hand ~14h
later. `e8da4a2` gave `overnight_drive.sh` the `START` knob that made parallel windows
possible without giving `scoped_run.sh` a matching mode.

**Fix.** A `--windows N` mode in `scoped_run.sh`: fan out N generation drivers over
disjoint `START` offsets, barrier on all of them, then run the adapter **once** and a
single eval over the merged window. The pieces all exist; only the barrier is missing.
The 4000–5999 window had the same shape (`eval_recovery_4000_6000.log` was also
hand-launched), so this is a recurring failure, not a one-off.

### Fixed (2026-07-21)

`scoped_run.sh` gained a `WINDOWS` knob (default 1 = the historical serial behaviour).
`WINDOWS=N` tiles `[START, START+TOTAL)` into N gap-free sub-windows
(`PER = ceil(TOTAL/WINDOWS)`, last clamped to the end), launches one `overnight_drive.sh`
per sub-window into the shared `OUTDIR` (each keyed by global start index, its own
`drive_<start>.log`), then **barriers on all of them** (`wait` per PID, warning on a
non-zero driver but proceeding — a partial window is still evaluable). Only after the
barrier does it run the adapter **once** and a **single** eval over the merged record —
the two steps that would race on the derived filename if run per-driver. `GEN_BUDGET`
is per-driver and drivers run concurrently, so generation finishes in ~`GEN_BUDGET`
regardless of N. Tiling + barrier verified against a stub (8-way → 6000..9500 ×500;
3-way → 1334+1334+1332); full wiring verified end-to-end on a 2-row/2-window slice.
The 6000–9999 regen is now one launch:
`START=6000 TOTAL=4000 WINDOWS=8 CONFIG=config/fullcorpus.yaml OUTDIR=... scoped_run.sh`.

---

## G5 — Case-mapping APIs are out of scope, so a real skew is unreachable {#g5}

The pipeline exercises five regex APIs. bun's case-**mapping** data and its regex
tables are at different Unicode versions — `"\u{16EAC}".toLowerCase()` is a no-op on
bun but maps to U+16EC7 on node — and bun self-reports `unicode=15.1 icu=75.1` while
its regexp tables answer as 17.0. Its ICU case data does not even have Garay
(Unicode 16.0). Recorded under F001's root cause.

No regex API can see this: `toLowerCase` is a `String` method.

**This is a scope decision, not a bug.** Adding `toLowerCase`/`toUpperCase` as API
surfaces is cheap — the harness-template machinery is already general — but those
APIs test the runtime's ICU tables rather than its regex engine, which is a different
claim than the project currently makes. Recommend **not** doing it: G3's case-varied
inputs reach the more interesting half of the same skew (3b) through the regex APIs
that are already in scope.

> **Update 2026-07-15 (`d1f3125`): the recommendation held, and the bet paid off.**
> G3b's case-varied inputs did reach that half of the skew through the existing regex
> APIs — it is now [F003](differential_findings/DISCREPANCIES.md#f003), confirmed on
> all five of them, with `chaos`'s `case_flip` as the op that got there. Declining to
> add case-mapping APIs cost nothing and kept the project's claim intact. What remains
> unreachable is only the narrow `toLowerCase` skew itself, which is a curiosity next
> to F003. **Recommendation unchanged: still decline.**

---

## G6 — Artifacts not reproducible from recorded provenance {#g6}

> **RESOLVED 2026-07-15.** The check was run. **The artifacts were never
> irreproducible — the regeneration recipe was wrong.** `regex_5354` reproduces
> **byte-for-byte, all 411 files**, on the pinned image, once it is generated the way
> it actually was. The lead recorded below was **correct on both counts**: the
> position dependence is real, and `3ab1fc3` does fix it. Details in
> [the resolution](#g6-resolved). What survives is a **small, real** provenance gap:
> the legacy windows' artifacts depend on chunk context that provenance does not
> record. **F002 is unblocked.**

Carried over unresolved from `differential_findings/HANDOFF_regex_5354.md`:
`regex_5064`'s original artifacts cannot be regenerated by the pinned image despite
byte-identical `base.fan`/`exec.fan` and identical provenance
(`exec.strings.jsonl` is 7012 bytes on disk, 4272 when regenerated). Ruled out:
run-to-run nondeterminism, CPU load, one preceding row, a later image build, and
config/seed/corpus drift. The unproven lead is that `48defb5`'s `_fuzz` ran its
estimate probe unseeded on a shared `fdo` object, making output depend on how many
rows preceded it in the process — if so, `3ab1fc3` already fixes it.

**Why it stays on this list:** if artifacts cannot be regenerated from recorded
provenance alone, provenance is incomplete, and no finding's inputs can be
independently reconstructed. That is a claim about the whole experiment, not one row.
The handoff's suggested check — regenerate `--start 5354 --limit 1` and diff against
`results-run-4000-5999/regex_5354/` — is still not run.

### Resolution (2026-07-15) {#g6-resolved}

**The recipe was the bug.** `--start 5354 --limit 1` is not how `regex_5354` was
generated. `overnight_drive.sh` runs `overnight_run.py` **one fresh process per
100-row chunk** (`CHUNK=100`, starts on multiples of 100), so `regex_5354` was
generated in chunk `--start 5300 --count 100`, with **54 preceding rows in its
process**. Regenerating it alone gives it a different in-process history, and
`48defb5`'s generation depends on that history. Same for `regex_5064`, which the
handoff records as "checked by regenerating it in isolation" — the identical
mistaken recipe, which is why both rows looked broken.

Reproduce the original conditions and it matches exactly. Rows after 5354 cannot
influence it, so `--start 5300 --count 55` suffices:

| | exec fuzz-string digest | 1st string |
|---|---|--:|
| original (`results-run-4000-5999/regex_5354/`) | `391895d5df49cd18` | 96 |
| regenerated, `48defb5`, `--start 5300 --count 55` | **`391895d5df49cd18`** | 96 |

**All 411 non-`.diff.json` files byte-identical** — 400 harnesses, 5
`strings.jsonl`, 6 `.fan`. Nothing about it is nondeterministic.

**The mechanism, and the fix, both confirmed.** Four runs of `regex_5354`, isolated
vs. in-chunk, on the old image and on HEAD:

| image | isolated (0 preceding rows) | in-chunk (54 preceding rows) | position-dependent? |
|-------|------------------------------|------------------------------|---------------------|
| `48defb5` | `445809212a4fa596` | `391895d5df49cd18` | **yes** — the bug |
| `d1f3125` (HEAD) | `445809212a4fa596` | `445809212a4fa596` | **no** — fixed |

So `3ab1fc3`'s forked child + `random.seed(seed)` per `_fuzz` call **does** fix it:
HEAD returns the same strings regardless of what preceded the row, and that answer is
the position-free one (identical to a row generated first in a fresh process).

Two dead ends worth recording so nobody re-runs them:

- **Python's global `random` is not the channel.** Churning it 1,000,000 times before
  generation changes nothing, on either image. The channel is Fandango's own state on
  the shared `fdo`, exactly as the lead said — HEAD is immune because each `_fuzz`
  forks a child and the parent never runs Fandango, so every row starts from pristine
  module state.
- **Comparing the two images on an isolated row proves nothing.** Both give
  `445809212a4fa596`; with zero preceding rows there is no position effect to expose.
  The discriminating test is in-chunk.

**The handoff's "1,064 preceding rows" for `regex_5064` is wrong** — chunking means it
had ~64, and `regex_5354` had ~54. That mis-estimate is probably why the "one
preceding row → identical" experiment read as exculpatory: the real gap was ~54 rows,
not ~1,064, so one row was a much weaker probe than it appeared.

### What actually remains (small) {#g6-remaining}

The strong claim in this section is withdrawn: findings' inputs **can** be
independently reconstructed, so nothing published is in question, and **F002 is
unblocked**.

The narrow claim stands: **for artifacts generated before `3ab1fc3`, the four recorded
provenance axes (commit, `config_sha`, seed, corpus) do not determine the output** —
chunk context is a hidden fifth input, and it is not recorded. Concretely:

1. **Document the recipe.** Regenerating a legacy row needs its chunk:
   `--start <floor(id/100)*100> --count 100`. Add this to the handoff and to any
   finding that cites pre-`3ab1fc3` artifacts. Zero code.
2. **Record chunk context in provenance** (`chunk_start`, `chunk_count`) so an
   artifact says how it was made rather than requiring a reader to know the driver's
   defaults. Small, and it is the actual fix to "provenance is incomplete".
3. **Nothing to fix in the generator.** `3ab1fc3` already landed; HEAD is
   position-independent, so every future window — including the chaos re-run — is
   reproducible from provenance alone. Item 2 is then belt-and-braces rather than
   load-bearing.

### Item 2 done (2026-07-30) {#g6-item2-done}

`config.set_chunk_context(start, count)` is declared once per process by each entry
point — `overnight_run.py` from its `--start`/`--count`, `run.generate_all` from the
window it was handed — and `provenance()` emits `chunk_start`/`chunk_count` into every
artifact header and run record. One fresh process per chunk means a process-level value
*is* the chunk's identity, so this is the natural scope rather than a compromise.

Two properties are pinned by `tests/test_provenance.py` because both would regress
silently. **The keys are emitted as `null` when undeclared, never omitted** — so "nobody
declared a chunk" is greppable and can't be misread as "generated as a whole window".
And **`config_sha` does not move**: it hashes the resolved config only, so adding these
keys leaves every window comparable across this commit, including against the recorded
6000–10050 run.

`chaos` (`d1f3125`) deliberately preserves this property: its mutants draw from a
`random.Random` seeded from `(seed, regex_id, api, seed_n)` and never touch global
state, so adding it cannot reintroduce a positional dependency.

---

## G7 — We generate only in-language strings; the bugs live just outside {#g7}

> **Fixed 2026-07-15 (`d1f3125`)** by `pipeline.chaos` — fix items 1–3 below. It
> found [F003](differential_findings/DISCREPANCIES.md#f003) on its first run, a bug
> this document listed as invisible. The diagnosis is kept as written; see
> [the fix, as built](#g7-built) at the end of this section for what shipped and what
> is measured.

Measured over the 6000–9999 window (252,078 strings, `py_re_matches` per string):

| does the generated string match the regex it came from? | share |
|---|--:|
| yes, exactly once | 85.7% |
| yes, ≥2 times | 12.8% |
| **no** | **1.5%** |

**98.5% of every input we generate is a positive example.** The 1.5% that don't match
are not deliberate negatives — they are incidental drift between Python `re` (which
drives generation) and JS semantics. Near-misses, boundary cases, and negative
examples are, by construction, absent: Stage 2 builds a grammar *of the regex's
language* and Stage 3 samples it.

**Both bugs found so far live outside the language:**

- `regex_5354` (bun anchor, F002 candidate) needs a **leading pad** — a prefix the
  regex does not match.
- `/\p{Lu}/iu` (bun property-escape folding, [G3b](#g3), now
  [F003](differential_findings/DISCREPANCIES.md#f003)) needs a **lowercase letter**
  — a character outside `\p{Uppercase_Letter}`.

And the correlation is right there in the artifacts. `matchAll` is the only API whose
grammar injects non-matching material (`<pad>`), which is why its strings contain ≥2
matches 55.4% of the time while the other four sit at ~1.3%:

| api | 0 matches | exactly 1 | ≥2 |
|-----|----------:|----------:|---:|
| exec / test / replace / split | ~1.5% | ~97.1% | ~1.3% |
| **matchAll** | 1.6% | 43.0% | **55.4%** |

**`matchAll` is also the only API that found `regex_5354`.** The one API that
generates outside the language is the one that found the bug that lives outside it.
That is one data point, not a law — but it is the only data point we have, and it
points the same way as both findings.

This also starves whole result classes. `test → false`, `search → -1`, `exec → null`,
`replace → no-op`, `split → [whole string]` are the *negative* halves of every API's
behaviour, and at 98.5% positive inputs we barely exercise any of them. An engine that
wrongly *finds* a match where there is none is close to undetectable today.

**Fix.** Generate a companion negative/boundary corpus per regex. Roughly in order of
cost:

1. **Mutate a matching string out of the language** — flip a character, delete one,
   truncate, duplicate. Cheap, no grammar work, and lands exactly on the boundary
   where backtracking and anchor bugs live.
2. **Affix non-matching material** — leading/trailing pad for *every* API, not just
   `matchAll` (this is [G3a](#g3), and it is what `regex_5354` needed).
3. **Case-flip for `i` variants** ([G3b](#g3) — what the bun folding bug needed).
4. **Complement sampling** — generate from a grammar of the complement language.
   Expensive and often ill-defined; do it only if 1–3 dry up.

Note (1)–(3) are string transforms over what Stage 3 already produces. They need no
new grammar machinery, and they preserve provenance (record the transform + the seed
string). Fuzzing luck is fine and is the point — the issue is that we currently draw
all our luck from one side of the boundary.

### The fix, as built (`d1f3125`) {#g7-built}

`pipeline.chaos` implements items 1–3. After Stage 3 fuzzes, each generated string is
perturbed `chaos_n` times (config, default 2) by one of seven ops — `delete`,
`insert`, `substitute`, `duplicate`, `transpose`, `case_flip`, `truncate` — and the
mutants are tested as ordinary cases. It is a post-generation string transform, as
predicted: **no grammar machinery was touched, and the eval needed no change at all**
(mutants are appended after the fuzz strings in one contiguous `n` space, so
`range(count)` picks them up).

Item 4 (complement sampling) was not built and should stay unbuilt until 1–3 dry up.

**One op per mutant, not a stack.** A single perturbation keeps the mutant *on* the
boundary — which is the interesting place — and keeps the recorded `mutation` label
legible enough to replay by hand.

**A mutant is not required to leave the language, and often doesn't.** That is
intended: deleting one `a` from `aaa` still matches `a+`, but it is still a string
the grammar may never have sampled. Which side of the boundary each mutant landed on
is now *measured* rather than assumed — `py_re_matches` is recorded per mutant
exactly as for a fuzz string. On the `regex_9921` evidence run, chaos put **22.5% of
its mutants (45/200) outside the language, against 0% for fuzz** on the same regex.
That is the gap this section is about, made visible in one number.

**What it found.** On its first run — `regex_9921`, chaos the only variable:

| | cases | value discrepancies |
|---|------:|--------------------:|
| chaos off | 400 | 4 (all F001) |
| chaos on (`chaos_n: 2`) | 1,200 | **59** |

The 59 split three ways: 51 are **F003** (bun, all from chaos), 7 are **F001** (4
fuzz — byte-identical to the recorded witnesses, the control that chaos didn't
disturb the fuzz population — plus **3 new** from chaos), and 1 input makes **all
three engines disagree at once**. So chaos did not just find its predicted target; it
also deepened an existing finding. Full analysis in
[F003](differential_findings/DISCREPANCIES.md#f003).

**Two things the build had to get right, both of which trace to gaps on this list:**

- **`origin` on every string record** (`fuzz`|`chaos`, plus `seed_n` + `mutation` for
  a mutant). This is load-bearing, not bookkeeping: the `py_re_matches == 0`
  miscompilation oracle in `scan_miscompilations.py` / `overnight_aggregate.py` reads
  a non-matching string as proof the transpiler mis-modeled the regex — which is
  exactly what a *working* chaos mutant looks like. Both scanners now filter on
  `origin` and report the excluded count. Without that field the feature would have
  reported itself as a generation bug. It is also [G2](#g2)'s lesson applied on the
  way in: an aggregate you cannot decompose is an aggregate that hides things.
- **Local seeding.** Mutants draw from a `random.Random` seeded from
  `(seed, regex_id, api, seed_n)` — never the global `random`. So a mutant depends
  only on its seed string and provenance, never on how many rows preceded it in the
  process. That is precisely the positional dependency [G6](#g6) suspects of making
  artifacts irreproducible, and it was cheaper to not introduce it than to debug it
  later. `tests/test_chaos.py` pins both properties.

**What is still open here.** Chaos has only been run on one regex. The 98.5% figure
above still describes the 6000–9999 window as recorded, and the blast radius of both
F001 and F003 is a floor until that window is re-run with chaos on.

---

## G8 — Provenance recorded no commit at all, and nothing checked {#g8}

> **Fixed 2026-07-30.** Found while preparing the next sweep, not by any test.

The `eval_headline_6000_10050.json` headline — 3,134 regexes, **6,945,794 cases**, 4,051
value discrepancies — records:

```
"git_commit": "unknown-CalledProcessError"
```

Every chunk record in that window says the same. So the largest run this project has
produced cannot be tied to the code that produced it, which is the first of the four
axes [G6](#g6) spent its length defending.

**Neither half of the cause is visible on its own, which is why it survived.** The run
bind-mounted the repo over `/app` — the normal way to run HEAD without a rebuild — and
that single act broke both links of `_git_commit`'s fallback chain at once:

1. `git rev-parse HEAD` failed with **`detected dubious ownership`** (exit 128): the
   tree is owned by the host uid, the container runs as root. A non-zero exit is
   indistinguishable from "not a git repo", so it fell through to the bake.
2. The same mount **shadowed** the image's `/app/.git-commit`, which correctly holds
   `d1f3125…`, with the host repo's — where that file does not exist. The bake read
   empty, and empty means unknown.

A pristine container resolves correctly (`d1f3125…`), and `docker/build.sh` had done its
job — the image was fine. Checking either the image or the code in isolation exonerates
both.

**Fix, and why it is not the obvious one.** `_git_commit` now passes
`-c safe.directory=*` (per-invocation; no global git config is touched, and the call
only ever reads a hash), so step 1 succeeds and reports the commit of the **mounted
tree**. That is not a workaround for the bake — it is the only correct answer. When the
repo is bind-mounted, *the code being executed is the host tree*, so falling back to the
image's baked commit would confidently record a hash for code that is not running. The
tempting fix — bake harder, e.g. into an env var a mount cannot shadow — would have made
provenance **worse**: it would have replaced an honest `unknown` with a precise lie.

**And a backstop, because the mechanism was never the weak part.** The chain worked as
designed; nothing *checked* it, and the cost surfaced only after 6.9M cases. `scoped_run.sh`
now preflights `config.recorded_commit()` and refuses to launch when it is empty or
`unknown-*` (`ALLOW_UNKNOWN_COMMIT=1` overrides for throwaway runs). It is deliberately
environment-agnostic — it asks the pipeline what it *would* record, here, now — so it
catches the next cause too, not just this one. Two seconds against a window's worth of
untraceable cases.

**What is not repaired:** the 6000–10050 artifacts themselves. Their `config_sha`, seed
and `corpus_sha` are intact, and the code is *almost certainly* `d1f3125` (the image
that was current), but that is an inference, not a record. Any finding citing that
window should say so.

---

## Expansion surface — APIs, parameters, flags, oracles {#expansion}

> **Update 2026-07-21 — the top of this list has landed** (for the next regen; the
> committed 6000–9999 artifacts predate it). Flags: `y`, `d`, `g` added to
> `flag_variants` (`d`/`v` first needed adding to the flag alphabets;
> `serializeMatch` now emits `.indices` spans under `d`). Parameters:
> `_REPLACE_TOKENS` and `_SPLIT_LIMITS_JS` extended to the ambiguous / `ToUint32`
> edges. New APIs: `String.match` (dual shape by `g`), `String.search` (index),
> `String.replaceAll` (TypeError-unless-global). Together: APIs 5→8, flag_variants
> 4→7, ~2.8× the case count of the 1.0M-case prior run. Still open here: `v`
> (unicodeSets), the `g`-on-non-matchAll *multi-call* statefulness (single-call
> `lastIndex` is observed now, looped exec is not), a `lastIndex` preset, and the
> metamorphic within-engine oracles below.
>
> **Update 2026-07-30 — the `lastIndex` preset and `v` both landed.** That closes
> every item in the "if only three things get done" list plus the two follow-ons, and
> leaves exactly two things open on this whole section: looped-exec multi-call
> statefulness, and the metamorphic / reference-implementation oracles.
>
> **`lastIndex` preset.** `presetBattery` in the shared harness skeleton: for a regex
> carrying `g`/`y`, the five read-only APIs (`exec`, `test`, `matchAll`, `match`,
> `search`) now run once per preset from the uniform ladder
> `[0, 1, floor(len/2), len, len+1]` and record **both** the outcome and the
> `lastIndex` the call left behind. The second half is the part that matters: it is the
> only way to observe `Symbol.search`'s save-and-restore and `Symbol.match`+`g`'s
> reset-to-0 — laws about state *after* the call that no value comparison can reach.
> Verified on all three engines: `search` restores lastIndex to the preset while its
> result stays invariant, `match`+`g` resets to 0, and a past-the-end preset yields
> `null` with lastIndex reset. A non-`g`/`y` regex bypasses the battery entirely, so
> its `value` stays **byte-identical** to pre-preset artifacts — the axis is purely
> additive. `replace`/`replaceAll`/`split` stay out: they own their own batteries, which
> presets would cross-multiply for no additional law.
>
> **One knock-on to expect in the ReDoS numbers.** `exec_ms` brackets the whole oracle
> body, so for a *stateful* variant of a batteried API it now sums **five** api calls
> instead of one. `redos_slow_ms: 1000` is therefore a ~5× easier threshold to cross on
> those variants (~25% of all `(api, flags)` combos), so candidate counts for
> `exec`/`test`/`match`/`search`/`matchAll` under `g`/`y` should be expected to rise
> without any engine getting slower. This is not new behaviour so much as newly
> widespread: `replace` has always summed 13 calls and `split` 11, so whole-oracle
> timing is the established contract and `redos_slow_ms` was already calibrated against
> it. The engine-specific *ratio* is unaffected — every engine runs the same five calls
> — so the differential signal, which is the one this project acts on, is unchanged.
> Worth remembering when comparing a new window's `redos.candidates` against the
> 6000–10050 run's 547.
>
> **`v` (unicodeSets)** required one real decision, not just a config line. `u` and `v`
> together are a `SyntaxError`, and `u` is required exactly for the `\p{...}`/`\u{...}`
> patterns `v` is *interesting* on — so unioning `v` onto the base, which is what every
> other modifier does, would have handed every property-escape regex `uv` and turned
> the entire axis into a throw all three engines agree on: maximum cost, zero signal,
> and it would have read as coverage. `regex_facts._canonical_flags` therefore makes
> `v` **supersede** `u` (sound: unicodeSets is a strict superset of unicode mode), so a
> `\p{L}` pattern gets a real `v` harness instead of a guaranteed throw. The validity
> gate deliberately still does **not** consult `v` ([G1](#g1) fixed under-reporting;
> gating on the *stricter* flag would over-correct and shrink the corpus), so a `v`
> variant that cannot construct is a comparable `SyntaxError` outcome — which is the
> signal wanted from that axis. On its first engine check the `v` axis immediately
> reproduced [F003](differential_findings/DISCREPANCIES.md#f003): `/\p{Lu}/iv` is
> `true` on node and deno, **`false` on bun**, exactly as this document predicted.

What follows is coverage we have never had. Ordered by value-per-unit-of-work.
Grounded in `src/pipeline/api_descriptors.py`, which is genuinely well-factored for
this: an API is one frozen `ApiDescriptor` row, and the core never branches on
`descriptor.api`, so most of this is data, not code.

### Flags — the cheapest wins in the whole document

`config.flag_variants` is `["", "i", "m", "s"]`. `requires_flags` can only ever
contain `u` (`regex_facts.py:364`). So **`g`, `y`, `d` and `v` are never tested** —
except `g` where an API mandates it (`matchAll`).

**`y` (sticky) — one line of config, and it activates oracle code that has never
run.** The `exec` oracle already reads:

```js
if (re.global || re.sticky) { value = {result: value, lastIndex: re.lastIndex}; }
```

Neither flag is ever set for `exec`, so this branch is dead: **0 of 3,767
`exec.diff.json` files contain a `lastIndex`**. Adding `"y"` to `flag_variants` lights
it up immediately. Sticky is also exactly where `regex_5354`-class bugs live — it
constrains the match to `lastIndex`, interacting with `^` and with `g`.

**`d` (hasIndices)** — adds `.indices` (and `.indices.groups`) to match objects: a
start/end span for every group. This is both new coverage *and* a strictly richer
oracle — it catches divergences where engines return the same matched *string* from a
different *span*, which `serializeMatch` cannot currently see.

**`g` on the four non-`matchAll` APIs** — `g` is not decoration; it changes semantics.
`replace` replaces all rather than first. `exec`/`test` become **stateful** across
calls via `lastIndex`. That statefulness is a classic engine-divergence area and we
have never touched it.

**`v` (unicodeSets, ES2024)** — the newest and least-settled flag: set difference
`--`, intersection `&&`, `\q{...}` string literals, properties-of-strings like
`\p{RGI_Emoji}`. We already know bun fails `/\p{Lu}/vi`. `u` and `v` together are a
`SyntaxError`, which the harness records as a comparable outcome — fine, not a skip.

### New APIs — one `ApiDescriptor` row each

Three widely-used `String` methods are simply absent:

| API | why it is not redundant |
|-----|-------------------------|
| `String.prototype.match` | **Different return shape depending on `g`**: without it, a match object like `exec`; with it, a flat array of strings and *no* index/groups. Nothing else we test has that dual shape. |
| `String.prototype.search` | Returns an index, ignores `g` — and per spec `Symbol.search` **saves and restores `lastIndex`**, a documented divergence area. |
| `String.prototype.replaceAll` | **Throws `TypeError` unless the regex is global** — a comparable error outcome, and a rule engines can get wrong. Otherwise shares `replace`'s token battery for free. |

Lower priority: invoking `RegExp.prototype[Symbol.replace/split/match/search]`
directly (tests the protocol rather than the `String` wrapper), and
`RegExp.prototype.compile` (legacy in-place mutation).

### API parameter values — extend batteries that already exist

`_REPLACE_TOKENS` and `_SPLIT_LIMITS_JS` already establish the "fixed uniform battery"
pattern, so these are list edits:

- **Replacement tokens.** Present: `[$&] [$`] [$'] [$$] [$1] [$<name>]`. Missing the
  ambiguous ones, which is where engines actually differ: **`$12` when only 1 group
  exists** (is it `$1` then `"2"`, or group 12?), `$0` (not special), `$99`,
  `$<nosuchname>` (empty vs literal), a trailing bare `$`, and `$<>`.
- **Split limits.** Present: `undefined, 0, 1, 1000000`. Missing everything that
  exercises **`ToUint32` coercion**: `-1` (→ 4294967295), `2**32` (→ **0**, so
  `split(re, 2**32)` returns `[]`), `2**32 - 1`, `1.5`, `NaN` (→ 0), `"2"`. Cheap, and
  coercion edges are a classic bug farm.
- **`lastIndex` preset.** With `g`/`y`, set `re.lastIndex = k` before `exec`. Entirely
  untested today (see the dead branch above).

### Oracles — the most interesting axis

**1. Observe `lastIndex` for every API, not just `exec`.** `matchAll` clones its
regex; `replace` with `g` resets `lastIndex`; `search` must restore it. Engines
disagree here and we would not see it. (Moot today — the one place we *do* observe it
never runs.)

**2. Metamorphic / within-engine consistency — catches bugs all three engines share.**
This is the methodologically significant one: a differential oracle is *structurally
incapable* of finding a bug every engine has. Laws, checkable inside one engine:

- `re.test(s)` ⟺ `re.exec(s) !== null`
- `s.search(re)` === `re.exec(s)?.index ?? -1`
- `s.match(re)` (no `g`) deep-equals `re.exec(s)`
- `s.replace(re, "$&")` === `s` — an identity law that must hold for every regex
- `[...s.matchAll(gre)][0]` ≈ `gre.exec(s)`
- adding `d` must not change `match`/`index`; adding a redundant `(?:)` must not change
  the result

**3. A spec-faithful reference implementation** (e.g. **engine262**, a JS interpreter
written to follow the spec literally) as a fourth target. This **directly fixes the
voting problem** the `regex_5354` handoff flags: node and deno both embed V8, so
"2 of 3 engines agree" is one implementation agreeing with itself. A spec reference
turns a *vote* into a *verdict*. Adding other independent engines (JavaScriptCore
standalone, SpiderMonkey, QuickJS, Hermes) improves the vote; a reference ends it.

**4. Unicode Character Database ground truth for `\p{...}`.** Compare property
membership against the UCD data files directly. This would have turned F001 from
"engines disagree" into "**deno is wrong**, node and bun are right" without needing
the era-ladder probe — and, unlike any differential test, it would catch a property
all three engines get wrong.

**5. Timing/ReDoS.** Catastrophic-backtracking divergence. Groundwork exists in
`analysis/notable_results/node_redos/`.

> **Partly built (this commit).** The harness now reports `exec_ms` —
> `performance.now()` around the api call only, so engine startup (node 30ms, bun
> 14ms, deno 20ms — engine-correlated, and fatal to a differential timing oracle) is
> excluded, as is `new RegExp` compilation. It is deliberately kept out of
> `_comparable()`, so a slow run can never fake a value discrepancy. Cases over
> `redos_slow_ms` **or** that timed out are re-executed serially once the pool drains
> and reported to `results/redos_<window>.json`, flagged `engine_specific` at a
> slowest/fastest ratio ≥ `redos_engine_ratio`.
>
> **Read the headline's zero correctly.** Before timing existed, ReDoS was a 20s
> cliff with nothing finer than `timed_out: true` behind it — and a timeout was folded
> into `defect_cases`, so that counter conflated "the harness broke" with "an engine
> backtracked", the second of which is the result we want. Timeouts are now their own
> disjoint counter: `defect_cases` means only the harness malfunctioned, and
> `timeout_cases: 0` means "nothing crossed 20s" — still **not** "no ReDoS", because
> the budget is a cliff and the cases below it are what `exec_ms` is for.
>
> The timeout trigger is the load-bearing half, and it is why `timed_out: true` was
> never sufficient on its own: the harness prints its envelope only *after* the api
> call returns, so an engine still backtracking at the budget is killed having
> reported **no `exec_ms` at all**. Measured on `/(a+)+$/` vs `"a"*31 + "!"`: node and
> deno (both V8) run for minutes and are killed at 20s; bun returns in **686ms**.
> Timing alone sees only bun's number, *under* the 1000ms threshold, and calls the
> case fine — discarding the sharpest engine-specific result available. Scoring a
> killed engine at the budget makes the recorded ratio a **lower bound** (29.4x here,
> marked `is_lower_bound`).
>
> **Still open, and the reason this is not "done":** none of it proves ReDoS.
> Catastrophic backtracking means runtime growing *superlinearly in input length*, and
> nothing here varies length. What is confirmed is **engine-specific slowness**.
>
> **Corrected 2026-07-17 — this said "the fuzzer does not emit long strings", and that
> is both false and the wrong diagnosis.** Measured over the 6000–9999 window's 49,733
> `test` strings: **p50 21 chars, p90 60, p99 111, max 285**; 61% of regexes have a
> string of ≥20 chars and 45% have one of ≥26. Length was never the problem. The
> problem is that the ~20 strings per regex are **unrelated to each other**, and a
> growth curve cannot be fitted across strings that share no shape — each carries its
> own constant factor. Twenty strings at lengths 8/21/44/60 say nothing about growth;
> five strings of *one shape* at n=5..9 say everything.
>
> So the gap is a length **family**, which is structural and cheap, not longer strings,
> which would be grammar work. It is closed by *deriving* a ladder from a string the
> fuzzer already emitted — demonstrated: a middle-deletion ladder over `regex_3910`'s
> raw 65-char fuzzer string recovers base 1.989 (R² 0.9999) with no pump identification
> and no grammar changes. [G7](#g7)'s `chaos` supplies the seed, since the ladder needs
> a **non-matching** string to force the full search (a matching input is measurably
> free — the same regex on `"a"*n` is flat at 0.05µs to n=40).
>
> And it needs no long executions at all: `notable_results/node_redos/micro_probe.py`
> classifies `regex_3910` as base 1.99 from a **24-char** input in milliseconds, and
> `/(a|aa)+$/` at base 1.624 — recovering φ=1.618, its true Fibonacci growth rate.
> See [F004](differential_findings/DISCREPANCIES.md#f004), which that work turned up.

### If only three things get done

1. **`flag_variants: ["", "i", "m", "s", "y", "d"]`** — a config line. Activates dead
   `lastIndex` oracle code, adds sticky (an anchor-bug-rich area), and enriches every
   match observation with `.indices`.
2. **`match`, `search`, `replaceAll`** — three `ApiDescriptor` rows against a
   deliberately general mechanism, covering the most-used API we do not test.
3. **The `$12`/`ToUint32` battery entries** — two list edits landing directly on known
   coercion-ambiguity bug farms.

All three are hours, not days, and none require touching the pipeline core.

---

## Suggested order

> **Revised 2026-07-30.** Almost everything that was on this list has landed. ~~G7 /
> G3~~ **done** (`pipeline.chaos`, `d1f3125`). ~~G6~~ **resolved**, and its
> [leftover item 2](#g6-item2-done) is now done too. ~~G1~~, ~~G2~~, ~~G4~~ **fixed**
> 2026-07-21. ~~The chaos re-run~~ **done** — 6000–10050, 6.9M cases. ~~Flags, the three
> `String` APIs, the parameter batteries, the `lastIndex` preset, `v`~~ all landed
> ([expansion](#expansion)). ~~G8~~ **fixed**. What is actually left:

1. **Write up F002** — unblocked since 2026-07-15 and now the oldest thing on the list.
   `HANDOFF_regex_5354.md` has the analysis ready to catalogue. The chaos re-run has
   since covered that row's range, so the [G3a](#g3) question — does the leading pad
   lift the candidate from 1 API to 5 — should be answerable from recorded artifacts
   rather than needing a fresh run.
2. **Re-read the 6000–10050 headline properly.** It has 4,051 value discrepancies, 485
   timeout cases, and 397 confirmed ReDoS candidates (230 engine-specific) that nobody
   has triaged against the known findings. This is the largest body of unanalysed signal
   the project has, and it is worth more than generating more of it. Note its
   [G8](#g8) caveat: no recorded commit.
3. **Sweep a genuinely new range.** Everything at or below 10049 has now been seen;
   3000–3999 is an unswept hole and 10050+ is open corpus (537,805 rows total). Cheap
   now that [G4](#g4)'s `WINDOWS` mode and the G8 preflight exist.
4. **The two structural bets** below — a spec-faithful reference implementation, and
   metamorphic within-engine oracles. These are the only items left that change what
   the experiment is *capable* of seeing, as opposed to how much of the corpus it has
   pointed at.
5. **Looped-exec multi-call statefulness** — the last of the cheap expansion items, and
   the only one the `lastIndex` preset did not subsume. Single-call `lastIndex` is now
   observed at five start positions; iterating `exec` to exhaustion still is not.
6. **G5** — recommend declining, and the bet already paid: G7 reached the interesting
   half of that skew through APIs already in scope (that is F003).

The two structural bets, worth more than any single item above: a **spec-faithful
reference implementation** (ends the V8-duopoly voting problem) and **metamorphic
within-engine oracles** (finds bugs no differential test can, by construction).

F003 sharpens the first of those. It is the first finding where **the spec picks a
winner**: node and deno are right, bun is wrong, and we know that from ES2024
§22.2.2.7.1 rather than from a 2-of-3 vote. Note the vote would have gotten this one
right — but it would have been node+deno, i.e. V8 agreeing with itself, for a bug that
happens to be in the non-V8 engine. That is the duopoly problem getting lucky, not
being solved.

Nothing here changes an existing finding's validity: F001 and the `regex_5354`
candidate are real on the inputs as they exist, and both have engine-level reproducers
independent of the pipeline. What these gaps affect is **coverage** — how much of the
corpus the experiment can actually speak for. The chaos result is the clearest
statement of that: the pipeline's headline for `regex_9921` went from 4 discrepancies
to 59 without a single engine, regex, or flag changing. Only the inputs did.

## G9 — ReDoS nomination fires on process starvation, not backtracking {#g9}

- **Measured on:** window 12050–15050, `results/redos_queue_12050_15050.json` (239 deferred
  nominations). Full triage:
  [`redos_nomination/TRIAGE_12050_15050.md`](redos_nomination/TRIAGE_12050_15050.md).

A row is nominated when **any single engine** exceeds the harness timeout *while the parallel
pool is saturated*. On a loaded box that condition is met by process scheduling, independently
of the regex.

**What it costs.** The 239 rows collapse to 26 regexes. Of those, **13 (79 rows) are
structurally incapable of superlinear backtracking** — at most one unbounded quantifier and no
quantified group, so there is exactly one way to match any prefix. They were queued anyway. The
clearest case is `regex_14049` = `[㐀-龿]`, a single character class, on the one-character input
`"鷽"`, recorded as a 20-second node timeout.

**Independent confirmation from the timeout pattern.** In the two non-exponential buckets the
timeouts are spread uniformly across engines (node 28 / deno 26 / bun 25, and bun 29 / node 24 /
deno 20) and **never hit more than one engine at a time** — 0 of 152 rows had all three time out.
A property of the *pattern* would slow all three; a property of an *engine* would hit the same one
repeatedly. Uniform-single-engine is neither: it is whichever process lost the scheduler lottery.

**The cost is not just noise, it is 9× wasted confirm time.** One regex (`regex_14648`) is 86 of
the 239 rows, so a per-row confirm re-measures the same regex 86 times. Re-run unloaded it takes
bun 3.96 s / node 5.84 s / deno 5.76 s against 15.1 s / >20 s / >20 s in the pool: the pool
inflated readings 3–4× and turned two finishing runs into timeouts.

### Fix — a sound static pre-filter, free

> If a pattern has ≤1 unbounded quantifier (`*`, `+`, `{n,}`) and no quantified group, it cannot
> exhibit superlinear backtracking. Never nominate it.

This direction is sound: it can only reject true negatives, so it cannot hide a real ReDoS. On
this window it removes 13 regexes / 79 rows before they are ever queued, at zero measurement cost.

**Second, cheaper tightening:** require **≥2 engines** over budget, or re-check a single-engine
timeout once before queuing. Either rule alone removes essentially all 152 rows in the two lower
buckets on this window.

**Not fixed by deferring.** `--redos-defer` correctly stops the pool's numbers being read as
findings, but the *queue* is still built from the starvation-contaminated predicate, so the
deferred list is 9× larger than the work it represents.

---
