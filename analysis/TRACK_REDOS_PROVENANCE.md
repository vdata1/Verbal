# Track: reporting universally-ReDoS regexes to the packages that ship them

**Status: OPEN, not started. Blocked on corpus provenance — see §2.** Opened 2026-08-12.

This is a **different finding class** from everything the pipeline currently reports, and
it is worth keeping separate rather than folding into the engine work.

## 1. The idea, and why the pipeline is blind to it

Everything this project reports is a *differential*: engine A disagrees with engine B, or
is dramatically slower. A regex that is exponential on **every** engine is not a
differential at all — `run_eval._confirm_redos`'s docstring calls it "a property of the
regex itself", keeps it in the artifact, and never flags it.

But that is precisely what a package-level ReDoS CVE is made of. The vulnerability is in
the library that ships the pattern and feeds it untrusted input, not in the engine. So
there is a whole bucket the pipeline deliberately discards for its own purposes which is
the *primary* material for a different kind of report.

`regex_14648` is the worked example: exponential at base ≈ 2.0 on node, deno, bun 1.3.14
and bun 1.4.0 alike (`redos_nomination/GROWTH_14648.md`). Nothing to tell an engine
vendor. Everything to tell whoever ships the pattern.

## 2. What blocks it today

### 2a. The corpus has no package identity — verified exhaustively

`data/uniq-regexes-8.json` is 537 805 JSONL entries with exactly five keys. Checked
across every entry, not sampled:

| field | non-empty |
|---|---:|
| `pattern` | 537 804 |
| `useCount_registry_to_nModules` | 537 805 — registry → **count**, never a name |
| `useCount_IStype_to_nPosts` | 12 918 — only `StackOverflowRegexSource` |
| `supportedLangs` | **0** |
| `type` | 537 805 |

`regex_id` → pattern is exact and lossless (`regex_id` is the 0-based line index; the
README says so and `regex_14648` = line 14648 confirms it). The missing edge is
**pattern → package**. We know one packagist module uses `regex_14648`. We cannot learn
which one from anything in this repo.

`data/regex_harvest.json` *does* carry `repo`/`repo_url`/`file_path`, but it is a
different and much smaller dataset — 8 222 rows over 6 repos — and does not contain the
confirmed-slow patterns. It is not a join partner.

### 2b. Most of the corpus is not JavaScript

Regexes present per registry, whole corpus:

| rubygems | npm | cpan | packagist | pypi | godoc | maven | crates.io |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 153 334 | 150 921 | 142 776 | 44 236 | 43 895 | 22 104 | 19 331 | 2 024 |

npm is ~28%. Everything measured here runs on V8/JSC, and an exponential blowup there
establishes nothing on its own for Onigmo, PCRE, Perl, `re`, or RE2 — Ruby 3.2+ memoizes,
RE2 cannot backtrack at all, and PCRE hits a backtrack limit and fails rather than hangs.
**Our own headline example is a packagist (PHP) pattern we have only ever run on JS
engines.** Any reporting pass must filter to npm first, or re-measure on the home engine.

### 2c. The confirm artifact cannot identify the candidates anyway

The tempting shortcut is "confirmed slow but never `engine_specific`". That set is 4
regexes (2 × npm, 1 × packagist used by 10 modules, 1 × cpan). **It is the wrong set.**

`regex_14648` is *not* in it — it is flagged `engine_specific` AND exponential on all four
engines. The two properties are orthogonal: `engine_specific` compares a ratio at one
string, while ReDoS is a growth class, and the confirm phase never varies length. Only
the curve fitter can classify.

Candidate sources, in order of value:

- the nominator's full-window sweep — 3 EXPONENTIAL + 49 POLYNOMIAL out of 3 761 `test`
  regexes in window 6000–9999 alone, which is far richer than the confirm's output;
- the 19 distinct regexes confirmed slow across all six windows, subject to a curve.

## 3. What would unblock it

1. **Recover the upstream corpus.** The schema fingerprint — exactly eight registries
   (hence "uniq-regexes-**8**") plus a `StackOverflowRegexSource` post count — matches the
   published polyglot regex corpus from the Davis et al. line of work on cross-language
   regex portability. *This is inference from the schema; the repo documents no origin —
   no `data/README`, no comment in `paths.py` or the configs.* If that is the source, this
   file looks like a **deduplicated projection** of it, which is exactly why it kept
   `nModules` counts and dropped the module lists. Confirm with whoever assembled `data/`,
   then re-join on the pattern to recover names.
2. **Filter to npm**, or re-measure survivors on their home engine.
3. **Growth-curve the survivors** with `redos_nomination/growth_family.py`. This step
   already exists and is validated. Find the axis **per regex** — on `regex_14648` the
   obvious family read SAFE and prefix growth was flat; all the cost was in the trailing
   whitespace. Presuming the axis would have produced a confident false negative.
4. **Check reachability.** A ReDoS is only a vulnerability when attacker-controlled input
   reaches the pattern. No artifact here carries call-site data, and this is the step that
   separates a report from noise.
5. **Check prior art before filing.** `regex_17570` was already fixed upstream before we
   looked at it; assume the well-known patterns are known.

## 4. Why it may still be worth it

Cheap to test and independent of the engine work: the whole `regex_14648` study was
minutes of engine time on a quiet box. If step 1 lands, steps 2–3 are mechanical over a
list that is already computed.

If step 1 does **not** land, the honest outcome is to close this track rather than file
reports naming no package or guessing at one. Nothing else here is blocked by it.
