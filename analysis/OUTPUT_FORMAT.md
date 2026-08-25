# Verbal output format — what a run leaves on disk, and how to read it

Reference for consuming the artifacts of a `scoped_run.sh` run. Everything below is relative to
the **results mount** — whatever you passed as `-v $RESULTS:/app/results`, or `results/` natively.
Written as `<results>/` throughout; substitute your own path. Nothing here depends on which
machine produced the run.

Schemas were read off completed runs and cross-checked against the code that writes them:
`eval/run_eval.py` (headline, diff artifacts, ReDoS), `src/pipeline/run.py` (run record statuses)
and `src/paths.py` (every filename). Where a field's meaning is a judgement call rather than a
type, the rationale is in the writer's docstring — those are worth reading before you build
anything that depends on the semantics.

Two conventions to internalize before anything else:

- **`<window>` is `<start>_<end>`**, where `end = START + TOTAL` — the half-open corpus row range
  `[start, end)`. Every top-level artifact is named for its window. There is no global
  `eval_headline.json`; never merge windows by overwriting.
- **Artifacts land at the mount ROOT, not in `OUTDIR`.** `OUTDIR` holds only the generation
  driver's own logs and chunk records. This surprises everyone once.

---

## 1. File inventory

```
<results>/
  eval_headline_<window>.json     Phase B headline: counts + per-cell discrepancy index   <- START HERE
  run_record_<window>.json        Phase A outcome per corpus regex (what got generated, what got skipped)
  redos_<window>.json             confirmed slow cases (written when REDOS_DEFER=0, or by confirm_redos.py)
  redos_queue_<window>.json       UNCONFIRMED nominations (written when REDOS_DEFER=1)  <- not findings yet
  regex_<index>/                  one dir per corpus regex that reached status "ok"
    base.fan                        the specialized Fandango grammar
    <api>.fan                       per-API grammar
    <api>.strings.jsonl             the generated inputs + their provenance
    <api>__<n>__<flags>.js          the harness actually executed (flags tag "none" = no flags)
    <api>.diff.json                 FULL per-case cross-engine evidence          <- the raw truth
  <OUTDIR>/                       e.g. run_20000/ — driver-side only
    chunk_<start:06d>.json          per-chunk generation outcomes (the resume unit)
    drive_<start>.log               per-driver generation log
    summary.json                    generation summary across that driver's chunks
    scoped_run.log                  the whole run's stdout, if you redirected it there
```

`generated_grammars/`, `generated_test_inputs/`, `generated_unit_tests/`, `diff_test_results/`
are created unconditionally by `paths.ensure_results_dirs()` and are **empty for a
`scoped_run.sh` run** — they belong to the older `src/main.py` entry point. Ignore them.

The eight APIs are `exec, match, matchAll, replace, replaceAll, search, split, test`.

---

## 2. `eval_headline_<window>.json` — the headline

```jsonc
{
  "engine_versions": {"node": "v26.5.0", "bun": "1.3.14", "deno": "2.9.1"},
  "window": {"start": 10050, "end": 11050},
  "regexes_evaluated": 926,        // only status=="ok" regexes are evaluated
  "units_done": 7408,              // a UNIT is one (regex, api) pair — the parallel work item
  "units_total": 7408,
  "complete": true,                // units_done >= units_total, scoped to THIS window only
  "totals": {
    "cases": 1037120,              // a CASE is one (regex, api, n, flags) cell
    "value_discrepancies": 1652,
    "defect_cases": 0,
    "timeout_cases": 3
  },
  "cache": {"reused": 0, "computed": 7408},   // --resume hits vs recomputes
  "discrepancies": [{"regex_id": "regex_10122", "api": "match", "n": 7, "flags": "iv"}, ...],
  "provenance": { ... },           // see §6
  "redos": {"candidates": 512, "confirmed": 478, "engine_specific": 431,
            "load_artifacts": 30, "unmeasured": 4}
}
```

**`complete: false` means the run was killed**, not that it failed — the headline is rewritten
atomically after every regex precisely so a killed run leaves valid, honestly-labelled JSON.
Check it before you trust any total.

**`discrepancies` is an index of CELLS, not of bugs.** One engine-level fact books hundreds of
entries: `regex_11383` failing to compile under `v` in bun is a single syntax fact that alone
books 480 cells (8 APIs × 60 strings). For scale, in one completed 1000-row window 1560 of the
1652 discrepancies (94%) were re-finds of a single already-known engine bug, and the window's
~5 distinct root causes came from 20 regexes. **Never report a raw discrepancy count as a bug
count.** Collapse first — see §7.

If the ReDoS phase was deferred, the `redos` block additionally carries
`"deferred": true, "queue_path": "..."` and `confirmed` will be 0. That is *not* the same as
"nothing found", and totalling `confirmed` across deferred and non-deferred windows is wrong.
The `redos` key is **absent entirely** while the run is still in the eval pool — meaning "not
computed yet", deliberately not written as zeros.

---

## 3. `<regex_id>/<api>.diff.json` — the raw evidence

The headline points here; this is where you go for any actual investigation.

```jsonc
{
  "regex_id": "regex_10000", "api": "exec", "pattern": "^<div>\\n  <div>\\n    <!-- ",
  "engine_versions": {...}, "provenance": {...},
  "num_strings": 3,
  "flag_variants": ["", "i", "m", "s", "y", "d", "g"],
  "results": [                       // num_strings × flag_variants cases, in (n, flags) order
    {
      "n": 0, "flags": "",
      "value_discrepancy": false, "any_defect": false, "any_timeout": false,
      "distinct_values": ["{\"ok\": true, \"value\": {...}}"],   // the distinct `comparable`s
      "runs": {
        "node": {
          "engine": "node", "exit": 0, "timed_out": false,
          "stdout": "...", "stderr": "",
          "canonical": {"api": "exec", "regex_id": "...", "ok": true,
                        "value": {"match": "...", "groups": [], "index": 0},
                        "exec_ms": 0.114},
          "comparable": "{\"ok\": true, \"value\": {...}}",
          "defect": false
        },
        "bun": {...}, "deno": {...}
      }
    }
  ]
}
```

### The three outcome axes, and why they are disjoint

This is the part worth getting exactly right before you aggregate anything.

| Axis | Definition | Meaning |
|---|---|---|
| **value discrepancy** | ≥2 distinct `comparable` values among engines that produced one | the regex-semantics signal — the thing you are hunting |
| **run defect** | `not timed_out and (exit != 0 or canonical is None)` | the *harness* malfunctioned; not a semantics signal, not compared |
| **timeout** | wall-clock budget blown | tracked on its own axis; an engine still backtracking when killed is the ReDoS tracker's sharpest result, not a malfunction |

`comparable` is the engine-independent serialization used for the diff: `{"ok": true, "value": ...}`
on success, `{"ok": false, "error": ...}` on a thrown regex error. An engine-thrown error is a
**comparable outcome** and is diffed like any value — engines disagreeing about *whether* a pattern
throws is a finding. `exec_ms` is deliberately excluded from `comparable`, so timing never fakes a
discrepancy.

Timeout **suppresses** defect (both of defect's disjuncts trip on a timeout unaided), so
`defect_cases` and `timeout_cases` never double-count the same case. Derive per-case verdicts from
the per-run fields rather than reading back a stored `any_defect`: artifacts written before the
timeout/defect split recorded `defect: true` on timed-out engines.

**Cross-engine votes are not majority votes.** node and deno both embed V8 — "2 of 3 agree" is one
implementation agreeing with itself. Use `tier_diff.py` (one engine at two JIT tiers) or `laws.py`
(single-engine metamorphic laws) when you need ground truth without a spec argument.

---

## 4. `run_record_<window>.json` — what Phase A produced

Phase B consumes this; it also tells you *why* a corpus row produced no results.

```jsonc
{
  "provenance": {...},
  "start": 10050, "limit": 1000,
  "counts": {"ok": 926, "unsatisfiable": 48, "not_js": 23, "error": 2,
             "surrogate_escape_unmodeled": 1},
  "outcomes": [
    {
      "regex_id": "regex_10050", "index": 10050, "status": "ok",
      "pattern": "...", "num_constraints": 3,
      "capture_group_rules": ["...", "..."],
      "regex_facts": {"anchored_single_match": false, "requires_flags": [],
                      "unsatisfiable_internal_anchor": false},
      "apis": [{"api": "exec", "pad": null, "flags": "", "degenerate": false,
                "anchored_single_match": false,
                "reason": "single-match base (min_matches=1); groups_must_participate: 2 group(s)",
                "num_strings": 60}, ...]
    }
  ],
  "source": "...", "source_outdir": "..."   // present when rebuilt by chunks_to_run_record.py
}
```

`status` values (`counts` contains only those that actually occurred):

| status | meaning |
|---|---|
| `ok` | generated; **the only status that gets evaluated** |
| `skipped_non_regex` | the corpus row isn't a regex (e.g. row 0 has `pattern: false`) |
| `not_js` | pattern isn't valid JavaScript regex syntax |
| `unsatisfiable` | no string can match (constraints contradict) |
| `no_inputs` | generation produced nothing within budget |
| `unsupported_unicode_property` | `\p{...}` the transpiler doesn't model |
| `surrogate_escape_unmodeled` | lone-surrogate escape outside the model |
| `error` | generation raised |

`regexes_evaluated` in the headline should equal `counts.ok`. If it doesn't, the eval didn't
finish the window.

---

## 5. ReDoS artifacts

The split exists because a timing taken while N workers saturate the cores is inflated by an
unknown factor — such readings are **nominations, not findings**.

**`redos_queue_<window>.json`** (`REDOS_DEFER=1`, the recommended mode) — `"status": "deferred"`,
plus `candidates`, `harnesses_missing`, and a `queue[]` of
`{regex_id, api, n, flags, observed_ms, observed_timeout, pattern, harness_path, harness_source}`.
`observed_ms` is the under-load reading and is frequently `{}`. **Nothing here is a result yet.**
Confirm it on a quiet box:

```bash
python3 eval/confirm_redos.py --queue results/redos_queue_<window>.json
```

It re-executes serially and emits `redos_<window>.json` in the same schema as the inline path, so
downstream consumers take either unchanged. Serial is the point, not a limitation — running the
confirm in parallel would reintroduce exactly the contention that made the nomination
untrustworthy. To go faster, split across boxes with `--shard i/n` and `--merge` the reports;
`--resume` and `--checkpoint-every` make a long confirm restartable.

**`redos_<window>.json`** — the verdict artifact:

```jsonc
{
  "window": {...}, "engine_versions": {...}, "provenance": {...},
  "slow_ms": 1000, "engine_ratio": 10.0, "caveat": "...",
  "candidates": 512,
  "confirmed": [{
    "regex_id": "...", "api": "matchAll", "n": 12, "flags": "g", "pattern": "...",
    "pool_ms":  {"bun": 1840.2},                 // under load — the nomination
    "pool_timeout": ["bun", "deno"],
    "serial_ms": {"bun": 9120.4, "node": 31.1, "deno": 28.7},   // quiet re-measure — the evidence
    "timed_out": ["bun"],
    "is_lower_bound": true,                      // killed while still backtracking: >= this
    "slowest_engine": "bun", "fastest_engine": "node",
    "ratio": 293.2,                              // slowest / fastest, serial
    "engine_specific": true                      // ratio >= engine_ratio: one engine, not the pattern
  }],
  "load_artifacts": 30,    // nominated under load, did not reproduce serially — DISCARD these
  "unmeasured": 4
}
```

Use `serial_ms`, never `pool_ms`. `engine_specific: true` is the interesting subset: a pattern
that is slow everywhere is a bad pattern, while one slow in a single engine is an engine bug.
`is_lower_bound: true` means the real time is worse than recorded.

Do not assume nominations taken at high load are throwaway. The working guess that "candidates
nominated above ~80% load are all artifacts" **did not survive contact** — on re-measure, the
deferred queues confirmed 848 cases between them. Confirm the queue; don't triage it by eye.

---

## 6. Provenance (on every artifact)

```jsonc
"provenance": {
  "git_commit": "d52c5231...",       // "unknown" / dirty-marked if the tree was dirty
  "config_sha": "b0e31920...",
  "seed": 0,
  "corpus": "data/uniq-regexes-8.json",
  "corpus_sha": "999fe71e...",
  "chunk_start": 10050, "chunk_count": 100,   // null on window-level artifacts
  "resolved_config": { seed, corpus, eval_slice, matchall_k, pad_candidates, flag_variants,
                       chaos_n, chaos_ops, chaos_alphabet, fuzz_n, fuzz_max_generations,
                       fuzz_timeout_s, neutral_count_timeout_s, redos_slow_ms,
                       redos_engine_ratio, engines }
}
```

Two things this is load-bearing for:

- **`--resume` reuses a `<rid>/<api>.diff.json` only when resolved config AND git commit AND
  engine versions all match.** Change `HEAD` mid-run and everything already computed becomes
  unreusable. Provenance is stamped from `git status --porcelain`, so editing tracked files
  during a run taints it. (`*.md` is gitignored wholesale, so new docs are safe; the handful of
  force-added tracked docs are not — check `git ls-files analysis/ | grep '\.md$'`.)
- **Comparing results across machines is only valid at identical `engine_versions`.** Different
  node/bun/deno versions ⇒ different artifacts, legitimately.

`flag_variants` differing between artifacts is normal and not corruption: `v` was added to the
config later, and per-API variants differ (`matchAll` always carries `g`). Read the variant list
from the artifact, not from the config.

---

## 7. Processing recipes

All snippets below run from inside the results mount (`cd <results>`) and need nothing but a
stock Python 3.

**Inventory what a run produced:**

```bash
python3 - <<'EOF'
import json, glob
for p in sorted(glob.glob('eval_headline_*.json')):
    d = json.load(open(p))
    w, t = d['window'], d['totals']
    print(f"{w['start']:>6}-{w['end']:<6} complete={str(d['complete']):5} "
          f"regexes={d['regexes_evaluated']:>5} cases={t['cases']:>9} "
          f"discrep={t['value_discrepancies']:>6} defects={t['defect_cases']:>4} "
          f"timeouts={t.get('timeout_cases','-'):>4} "
          f"redos={d.get('redos',{}).get('confirmed','-')}")
EOF
```

(`.get` on `timeout_cases` is not defensive padding — headlines written before the
defect/timeout split lack the key entirely. Same for `redos`.)

**Collapse cells into root causes** (do this before counting anything as a bug). The helper
scripts run from the repo root, not the results mount:

```bash
python3 analysis/eval_help_scripts/dedupe_headline.py <results>/eval_headline_<window>.json
#   --redos <results>/redos_<window>.json    fold the ReDoS report in
#   --json                                   machine-readable output
```

Clusters by `(regex_id, kind, engine partition)` and reports alongside the raw counts without
mutating them. It still reports one bug once per corpus witness, so two clusters can be the same
bug; `analysis/eval_help_scripts/reduce.py` takes it further, reducing a finding to a minimal
`(api, pattern, flags, input)` repro — **two witnesses that reduce to the same repro are the same
bug**, whatever their original patterns looked like.

**Pull the evidence for one discrepancy:**

Every entry in a headline's `discrepancies` list is a coordinate into a diff artifact. Take the
first one and print what each engine actually said:

```bash
python3 - <<'EOF'
import json
HEADLINE = "eval_headline_<window>.json"

entry = json.load(open(HEADLINE))['discrepancies'][0]     # or pick any entry
rid, api, n, flags = entry['regex_id'], entry['api'], entry['n'], entry['flags']

d = json.load(open(f"{rid}/{api}.diff.json"))
c = next(c for c in d['results'] if c['n'] == n and c['flags'] == flags)
print(f"{rid} {api} #{n} [{flags or 'none'}]")
print("pattern:", d['pattern'])
for engine, r in c['runs'].items():
    print(f"  {engine:5} exit={r['exit']} timeout={r['timed_out']} -> {r['comparable']}")
EOF
```

The harness that produced it is `<rid>/<api>__<n>__<flags or "none">.js`; the input string is line
`n+1` of `<rid>/<api>.strings.jsonl` (line 1 is a `kind: "meta"` header carrying `count`,
`flag_variants` and provenance; string lines carry `origin` — `fuzz` or `chaos` — plus `mutation`,
`seed_n`, and `py_re_matches`, Python's opinion on whether it matches).

**Ship the divergent slice to whoever is processing it.** A results tree is tens of GB and
mostly agreement; the interesting part is a few MB. `collect_discrepancies.py` bundles every
discrepant harness plus its evidence into one self-contained, pushable directory (read-only —
it never touches the results tree):

```bash
python3 analysis/eval_help_scripts/collect_discrepancies.py \
    --results <results> --out <bundle-dir>
#   --window START_END     one window only (repeatable); default = all complete windows
#   --per-cluster N        ship at most N cells per cluster; cluster COUNTS stay exact
#   --allow-incomplete     also collect a killed run's window (complete=false)
```

It writes `MANIFEST.json` (windows, engine versions, provenance, misses), `clusters.json` (cells
grouped by `(regex_id, api, engine partition)` — the triage view), `evidence.jsonl` (one record
per cell: full diff case + the input string + harness path), `harnesses/` (the exact `.js`
executed) and the headline verbatim. Measured on a real window: 1652 cells → 63 clusters,
39.4 MB at full fidelity, 2.1 MB at `--per-cluster 3`.

**That collector ships the value slice only** — it starts from the headline's `discrepancies`
and never opens a `redos_*` file, so a bundle made with it carries none of the run's timing
side. `collect_redos.py` is the other half:

```bash
python3 analysis/eval_help_scripts/collect_redos.py \
    --results <results> --out <bundle-dir>
#   --window START_END       one window only (repeatable); default = every ReDoS window
#   --per-regex N            ship at most N confirmed rows per regex; COUNTS stay exact
#   --strip-queue-source     drop embedded harness_source (~8x smaller, no longer self-contained)
```

It copies `redos_<window>.json`, `redos_queue_<window>.json` and any `.ratio_split.json`
verbatim, and adds `rows.jsonl` (each confirmed row + its input string + harness path),
`by_regex.json` (rows folded to `(regex_id, api)` with the worst serial time) and `harnesses/`.
Each window is labelled `deferred` / `confirmed` / `both` — **a deferred window is nominations,
not results**, and since queue entries embed `harness_source` it can be confirmed on the
receiving box instead of the originating one. No classification is recomputed: the manifest
tallies the fields the artifact carries and reports `split_fields_present: false` for artifacts
written before the measured/lower-bound split, which is the cue to run `backfill_ratio_split.py`
rather than read `engine_specific` as a finding count.

**Reconcile coverage** — per-window `run_record.counts` against `<OUTDIR>/summary.json`
(`chunks`, `regexes_covered`, `coverage_ranges`, `status_counts`, `total_strings`, `nonmatching`,
`regexes_with_nonmatching`). Scattered per-row holes are usually legitimate non-`ok` statuses;
verify against the record before treating one as a gap.

---

## 8. Traps

1. **Check `complete` first.** `scoped_run.sh` exits 0 even when Phase B is SIGKILLed (an OOM
   leaves a truthful `complete: false` headline and a zero exit status).
2. **Raw discrepancy counts are cell counts.** Off by two orders of magnitude as bug counts.
3. **A deferred `redos` block is not a zero result.** Check `deferred`/`queue_path`.
4. **`load_artifacts` are discards**, not weak findings.
5. **node and deno are both V8.** A 2-vs-1 split with bun alone on one side is one engine
   disagreeing with one implementation, not with two.
6. **Never merge windows by filename collision.** Two runs into one results tree with the same
   window silently overwrite; give every run its own `OUTDIR` and its own results mount.
7. **A filename with anything extra in it was renamed by hand.** The tool only ever writes
   `eval_headline_<start>_<end>.json`; a name like
   `eval_headline_<start>_<end>.partial_oom_28750.json` is a human preserving a partial before a
   rerun overwrote it. Glob on the exact pattern, or you will read a superseded partial as
   current.
8. **A burst of defects at the very start of a resumed Phase B is a thundering herd, not a bug.**
   On resume every worker launches at once and the first handful of engine subprocesses lose the
   race for resources. A recorded 5000-row window's entire defect count — 13 cases — was exactly
   this: the first 13 events after a resume, none of which reproduce. If defects cluster at the
   head of a run, re-execute them serially before reporting anything.
9. **Missing `run_record`?** It is written only after the whole generation loop finishes, so a run
   killed during Phase A leaves a full artifact tree and no record. Rebuild rather than
   regenerate: `chunks_to_run_record.py` (from `<OUTDIR>/chunk_*.json`) or
   `artifacts_to_run_record.py` (from the on-disk `regex_*/` tree).
