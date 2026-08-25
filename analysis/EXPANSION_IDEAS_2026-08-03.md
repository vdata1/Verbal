# Extension ideas — what is *not* already in EXPERIMENT_GAPS

**Written:** 2026-08-03 · Companion to [`EXPERIMENT_GAPS.md#expansion`](EXPERIMENT_GAPS.md),
which already covers: flags (`y d g v` — landed), the three `String` APIs (landed),
replacement/split/lastIndex batteries (landed), looped-exec statefulness (open),
metamorphic within-engine laws (open), a spec-faithful reference implementation (open),
UCD ground truth for `\p{...}` (open), and the ReDoS length-family (open).

Everything below is an axis that document does **not** contain. Grounded in the fuzzing /
testing literature, ordered by yield per unit of work.

---

## 0. The honest framing first

The pipeline's *discovery* rate is not the bottleneck right now. As of today there are
**six drafted-but-unfiled bug reports**, 239 unconfirmed ReDoS nominations, and a headline
whose raw count over-states unique bugs by ~80×. Klees et al. (CCS 2018, *Evaluating Fuzz
Testing*) is the canonical statement of this failure mode: crash counts are not bug counts,
and a fuzzer evaluated on raw findings will be tuned in the wrong direction.

So the highest-leverage items here are **§1 (automated reduction) and §2 (pattern
mutation)** — one multiplies triage throughput, the other multiplies discovery *per corpus
row* rather than requiring more corpus. Everything after that is genuine but secondary.

---

## 1. Automated test-case reduction — and dedup by *reduced* repro ⭐

**Not in EXPERIMENT_GAPS at all.** This is the biggest operational win available.

Today every finding is reduced by hand. The two bugs found in window 12050–15050 each took
a manual reduce-and-probe cycle to get from "587 cases on `regex_14680`" to
`/[\s\t\p{C}]/v`. `dedupe_headline.py` clusters by `(regex, kind, engine-partition)`, which
is why one bug with 34 witnesses reads as 34 clusters.

**Build ddmin** (Zeller & Hildebrandt, *Simplifying and Isolating Failure-Inducing Input*,
TSE 2002) with the differential itself as the interestingness predicate. Reduce along three
axes simultaneously: the **pattern** (syntax-guided, à la Perses — Sun et al., ICSE 2018 —
so intermediate candidates stay parseable), the **input string**, and the **flag set**.
C-Reduce (Regehr et al., PLDI 2012) is the reference for how much this pays off in a
compiler-bug workflow, which is structurally the same problem.

Then **cluster by the reduced triple, not by corpus id**. That single change would have
collapsed this window's 34 `gv` witnesses into one automatically, and emitted a file-ready
repro with no human in the loop.

Cost: a few days. Payoff: it attacks the amplification problem at the root instead of
reporting alongside it, and it turns "write up a finding" from an afternoon into a review.

---

## 2. Mutate the *pattern*, not just the input ⭐

**The whole mutation story today is `pipeline.chaos` on strings.** Patterns are immutable —
the experiment can only ever test regexes that literally appear in the corpus. That is a
large blind spot, and there are two distinct ways to exploit it.

### 2a. Semantics-*preserving* rewrites → a single-engine oracle (EMI)

Le, Afshari & Su (*Compiler Validation via Equivalence Modulo Inputs*, PLDI 2014) found
hundreds of GCC/LLVM bugs by mutating programs in ways that provably cannot change
behaviour, then checking the output did not change. The regex analogue is direct and cheap:

```
r          ≡  (?:r)  ≡  r{1,1}  ≡  (?:r|r)
[aa]       ≡  [a]                     [a-a]     ≡  [a]
(?:)r      ≡  r                       r(?=)     ≡  r
[abc]      ≡  [cba]  (class member order is irrelevant)
(x)        ≡  (?:x)  modulo the groups array
```

Any behavioural difference is **a bug in that one engine**, found without a second engine
and without a spec reference. This is the pattern-axis counterpart to the metamorphic laws
EXPERIMENT_GAPS already lists — all of which are on the *input/API* axis. It also
multiplies every corpus row into N self-checking variants, so it scales discovery without
needing more corpus.

### 2b. Semantics-*changing* mutations with a known direction

Monotonicity laws, also single-engine:

- `r` → `r|x` can only **add** matches: `r.test(s)` ⟹ `(r|x).test(s)`
- `[abc]` → `[ab]` can only **remove** them
- `a{2,4}` → `a{2,5}` can only add
- greedy → lazy cannot change *whether* a match exists at a given start, only its extent

Violations are sound bug reports. Related: **MutRex** (Arcaini, Gargantini & Riccobene) uses
regex mutation plus *distinguishing strings* — inputs on which the original and mutant
differ — as a test-generation strategy; that is precisely the boundary input `chaos`'s
uniform random edits reach only by luck.

---

## 3. The corpus cannot contain the newest syntax — synthesize it ⭐

`flag_variants` adds the **`v` flag** to corpus patterns, but v-mode's *own* syntax is set
notation, and a corpus of real-world regexes predates it. Measured on the actual corpus
(537,805 patterns):

| Construct | Occurrences |
|---|---:|
| `\q{...}` (v-mode string literals) | **0** |
| lookbehind `(?<=` / `(?<!` | 5,754 (1.07%) |
| backreference `\1`–`\9` | 3,862 (0.72%) |

So **set difference `--`, intersection `&&`, `\q{...}`, and properties-of-strings like
`\p{RGI_Emoji}` are never tested at all** — and the pipeline still found a v-mode class-union
bug today by accident, purely from the flag being applied to ordinary patterns. That is a
strong signal that directly targeting the construct would pay.

Add a **synthetic pattern generator** (a small grammar, not corpus-derived) for:

- v-mode set operations: `[\p{L}--[aeiou]]`, `[\w&&\p{ASCII}]`, `[\q{abc|d}]`, nested/chained
- ES2025 **inline modifiers**: `(?i:...)`, `(?-i:...)`, nested and conflicting
- ES2025 **duplicate named groups** in alternatives: `(?<y>a)|(?<y>b)`
- `RegExp.escape` (ES2025) — a brand-new API, and a natural round-trip oracle:
  `new RegExp(RegExp.escape(s)).test(s)` must be `true` for **every** string `s`

New syntax is where engines are least settled and test suites thinnest; this is where a
fuzzer has the biggest edge over hand-written conformance tests.

---

## 4. Intra-engine differential: JIT vs interpreter ⭐

EXPERIMENT_GAPS frames the V8-duopoly problem as needing *more voters* (a reference
implementation, more engines). There is a second, much cheaper exit that it does not
mention: **run the same engine in two configurations and diff it against itself.**

- V8 (node, deno): `--regexp-interpret-all`, `--no-regexp-tier-up`, `--regexp-tier-up-ticks=N`
  (deno: via `--v8-flags=...`)
- JSC (bun): the JSC option surface, e.g. disabling the RegExp JIT

Why this is strong:

1. **No voting problem.** If one engine's interpreter and its own JIT disagree, exactly one
   of them is wrong — by construction, with no spec reasoning and no majority needed.
2. **It finds the highest-severity class**: JIT miscompiles, which are also the most
   valuable to report upstream.
3. It costs a flag, not a new engine binary, and reuses the entire existing harness.

Tier-differential is standard practice in JS-engine fuzzing (Groß's Fuzzilli and the
Project Zero work around it lean on it heavily). It composes with everything else here: run
it over the same harnesses already being generated.

---

## 5. Stratify the corpus by *feature*, not by index

Windows are contiguous corpus index ranges, which correlate with nothing semantic. At the
natural frequencies above, a 3,000-row window contains roughly **32 lookbehind patterns and
22 backreferences**. Those are exactly the constructs where engines diverge most, and they
are being sampled at ~1%.

`regex_facts.py` already parses every pattern, so the feature index is nearly free. Then:

- **Stratified windows** — sample by construct (lookbehind, backref, nested quantifier,
  named groups, property escapes, `{n,m}` bounds) instead of by index. Same compute, ~100×
  the density on rare constructs.
- **Corpus distillation** — cluster patterns by normalized AST and test one representative
  per cluster, demoting the rest to confirmation-only. Directly attacks amplification from
  the input side (cf. Rebert et al., *Optimizing Seed Selection for Fuzzing*, USENIX
  Security 2014).
- **Swarm testing** (Groce et al., ISSTA 2012) — randomly *disable* feature subsets per run
  (flag sets, chaos ops, alphabet subsets) instead of always running everything. Reliably
  beats "all features always on" for diversity, and is a config change.

---

## 6. Feedback: guide generation by output-difference novelty

Generation today is one-shot and blind — grammar + chaos, no signal flows back. The natural
fit is not coverage-guided fuzzing (needs instrumented engines) but **NEZHA** (Petsios et
al., IEEE S&P 2017), whose *δ-diversity* guides mutation toward inputs producing **new kinds
of output disagreement** between implementations, using only the outputs already collected.

The pipeline already computes a per-case partition (which engines agreed). Define a
signature over `(api, flags, partition, divergence kind)` and prioritize mutating around
cases whose neighbours produced *novel* signatures. This is the largest architectural change
on this list — batch → feedback loop — so it belongs after §1–§4, but it is the item with
the highest ceiling.

---

## 7. Sound oracles that need no second engine

Additions to the metamorphic list already in EXPERIMENT_GAPS (all single-engine):

- **`d`-flag internal consistency:** `s.slice(...m.indices[i]) === m[i]` for every group,
  including named. Free, and validates the `d` output the harness already serializes.
- **Global-exec invariants:** for a non-empty match under `g`, `m.index + m[0].length ===
  re.lastIndex`; successive `matchAll` results must be non-overlapping and strictly
  increasing in `index`.
- **Sticky ≡ anchored-slice:** `re_y.exec(s)` at `lastIndex = i` must agree with
  `/^(?:src)/.exec(s.slice(i))` (modulo lookbehind and `^`/`m`). **This law alone would have
  caught the sticky-`.*` bug with a single engine** — worth adding for that reason alone.
- **Round-trip:** `new RegExp(re.source, re.flags)` must behave identically to `re`; likewise
  `eval(re.toString())`. Catches `source`-escaping bugs (`/` in class, line terminators,
  the empty-regex `(?:)` rule).
- **Membership-only cross-language oracle.** Whether a string matches *at all* is
  semantics-independent across backtracking and automaton engines, even though *which*
  match they pick is not. So RE2/Go, Rust `regex`, and Python `re` can serve as ground truth
  for `test` on the common syntactic subset — catching bugs **all three JS engines share**,
  which no JS-only differential can. (Davis et al., *Why Aren't Regular Expressions a Lingua
  Franca?*, ESEC/FSE 2019, maps the portability pitfalls to respect here.) The `py_re`
  neutral-count machinery already exists in generation; this reuses it as an oracle.

---

## 8. ReDoS: nominate statically, not by wall-clock

The current nominator is timing-based, which is why 239 candidates are sitting unconfirmable
and why absolute milliseconds do not survive a change of box. The literature nominates
**structurally** instead:

- Detect exponential / polynomial NFA ambiguity to *prove* a pattern is vulnerable
  (Weideman et al.; Wüstholz et al., *Rexploiter*, TACAS 2017).
- Such an analysis **synthesizes the pump string**, which simultaneously closes the
  length-family gap EXPERIMENT_GAPS documents: an attack string is by construction a
  pumpable family, so the growth curve `micro_probe.py` fits comes for free.
- ReScue (Shen et al., ASE 2018) is the genetic-search alternative when static analysis is
  inconclusive.

This flips ReDoS from "measure and hope the box is quiet" to "prove, then measure to
confirm" — and a proven pump is a far stronger bug report.

**Also cheap:** replace wall-clock with a **step/backtrack counter** where the engine exposes
one. Counts are box-independent, so they survive the sharding problem entirely.

---

## 9. Engine-version ladder, automated

F001 needed a manual "era-ladder" probe to establish which Unicode version deno shipped.
Systematize it: re-run any confirmed reduced repro against N historical Docker tags per
engine to get a **regression window** automatically. That is the first thing an upstream
maintainer asks for, and with reduced repros (§1) each probe is milliseconds.

---

## Suggested order

1. **§1 automated reduction + dedup by reduced repro** — unblocks the current backlog and
   every future window.
2. **§2a EMI-style pattern rewrites** — new bug class, single-engine oracle, reuses the
   whole harness.
3. **§4 JIT-vs-interpreter differential** — a flag, and it sidesteps the duopoly problem.
4. **§3 synthetic v-mode / ES2025 pattern generator** — where the engines are least settled.
5. **§5 feature stratification** — same compute, far higher density on divergent constructs.
6. **§7 the single-engine laws** — cheap, and one of them retro-catches a known bug.
7. **§6 δ-diversity feedback** — highest ceiling, largest rewrite; do last.
