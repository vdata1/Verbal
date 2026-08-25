# Handoff — investigate the `regex_5354` discrepancy (candidate F002)

> **STATUS LINE BELOW IS STALE.** This *was* catalogued: it is **F002** in
> `DISCREPANCIES.md` (confirmed, Yarr JIT miscompile), which cites this document as its
> evidence. Still true as of 2026-08-12: **not reported upstream** — see
> `../bug_reports/FILING_PLAN.md`, where nothing has been filed yet.
>
> Keep this file where it is: three docs cite it by path.

**Status:** reproduced and minimised; root cause hypothesis confirmed by live probe.
Not yet catalogued in `DISCREPANCIES.md`, not yet reported upstream.
**Prepared:** 2026-07-14. **Evidence:** [`regex_5354__bun_anchor_hoist/`](regex_5354__bun_anchor_hoist/)

> **Unblocked 2026-07-15.** The reproducibility question that gated writing this up is
> resolved (see the ✅ note in *Known gaps* below, and
> [EXPERIMENT_GAPS G6](../EXPERIMENT_GAPS.md#g6-resolved)): `regex_5354`'s artifacts
> reproduce **byte-for-byte, all 411 files**, once regenerated with their chunk
> context. Nothing now blocks cataloguing this as F002. Two notes for whoever does:
> (1) F002 is still the right number — [F003](DISCREPANCIES.md#f003) was confirmed
> first but took the next free one rather than renumber this handoff; (2) F003 shares
> this finding's split (node+deno vs bun = V8 vs JSC), so the "not a 2-1 vote"
> argument below now covers two findings, not one.

---

## TL;DR

**bun 1.3.14 misses matches at index > 0 when the pattern contains a `^` inside a
group that can match zero times and the `m` flag is absent.** node v26.5.0 and deno
2.9.1 both return the match; bun returns none. All three engines exit cleanly, so this
is a **value discrepancy**, not a run defect.

Minimal reproducer — a 9-character regex:

```js
Array.from("ay".matchAll(/(?:^x)*?y/g))
// node v26.5.0 -> [ "y" @ 1 ]   (correct)
// deno 2.9.1   -> [ "y" @ 1 ]   (correct)
// bun 1.3.14   -> [ ]           <-- WRONG
```

Per spec the group matches zero times, so `^` need never be satisfied and `y` at index
1 must match. bun is the outlier.

---

## Why this is not "3 engines voted 2-1"

**node and deno both embed V8. bun embeds JavaScriptCore.** So node+deno agreeing is
*one* implementation agreeing with itself, not two independent confirmations. The real
split here is **V8 vs JSC**, which is consistent with a genuine engine-family semantic
difference.

Note this is the mirror image of [F001](DISCREPANCIES.md#f001) (node+bun ✓ vs deno ✗).
F001 splits *within* V8 (node vs deno), which is why it reads as a Unicode-table/ICU
version difference rather than an algorithmic one. Worth keeping this distinction
explicit in the write-up — a naive "2 out of 3 engines agree" framing would be wrong
for both findings, in opposite directions.

---

## The original finding

- **Run:** rows 4000–5999 of `data/uniq-regexes-8.json`, corpus_sha `999fe71e…`,
  config `config/fullcorpus.yaml` (config_sha `d769e16a…`), seed 0, git_commit
  `48defb5`. Results dir: `results-run-4000-5999/`.
- **regex_5354** — an SRT subtitle-block parser:

  ```
  (.+)\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\n((?:^.*$\n)*?)\n
  ```

  The `^` lives in `((?:^.*$\n)*?)` — a **lazy** group, so it readily matches zero times.
- **40 discrepant cases, all `matchAll`,** and the flag split is total:

  | flags | discrepant cases |
  |-------|-----------------:|
  | `g`   | **20 / 20** |
  | `gi`  | **20 / 20** |
  | `gm`  | 0 / 20 |
  | `gs`  | 0 / 20 |

  `m` makes it vanish (that is the tell), `i` is irrelevant.
- Concrete case (`n=0`, flags `g`, input in `matchAll__0__g.js`): node and deno both
  return one match `"K\n02:04:29,720 --> 64:81:75,693\n\n"` at **index 50**; bun returns
  `[]`. Group 3 captures `""` — the lazy group matched **zero** times, so `^` is never
  required.

## Root cause hypothesis (probe-confirmed)

> JSC treats a `^` occurring inside a zero-matchable group as if it anchored the whole
> pattern, and so refuses any match at index > 0 when `m` is absent.

`probe_output.txt` (live, pinned engines) supports it and rules out the obvious
alternatives:

| case | node | deno | bun |
|------|:----:|:----:|:---:|
| `/(?:^x)*?y/g` on `"ay"` | `y`@1 | `y`@1 | **NO MATCH** |
| `/(?:^x)?y/g` on `"ay"` | `y`@1 | `y`@1 | **NO MATCH** |
| `/(?:^x)*y/g` on `"ay"` | `y`@1 | `y`@1 | **NO MATCH** |
| `/^y/g` on `"ay"` — *control: genuinely anchored* | none | none | none ✓ |
| `/(?:^x)*?y/gm` — *control: `m` present* | `y`@1 | `y`@1 | `y`@1 ✓ |

The controls matter: bun handles a real `^` anchor correctly, and is correct once `m`
is set. So this is not "bun is broken on `^`" — it is specifically the
zero-matchable-group + no-`m` combination. It reproduces with `*?`, `?` and `*`, so it
is not about laziness.

## The pipeline is under-reporting this

Only `matchAll` flagged it. The other four APIs ran the same regex and found nothing:

| api | discrepant | flag variants |
|-----|-----------:|---------------|
| exec, test, replace, split | 0 / 80 each | `["", "i", "m", "s"]` |
| matchAll | **40 / 80** | `["g", "gi", "gm", "gs"]` |

**Not a semantic difference between the APIs — an artifact of input shape.** The
`matchAll` specialization emits `<start> ::= <pad> (<m> <pad>){2,K}`, so its strings
begin with a pad (here `"\n"`) and the match lands at index 50. The `exec` strings
start with the match at **index 0**, where `^` is satisfied and bun agrees. The bug
needs a match at index > 0 to appear.

So the true blast radius is wider than the headline suggests: `exec`/`test`/`replace`/
`split` would diverge too on inputs with a leading pad. Worth considering whether the
non-`matchAll` specializations should also explore a leading pad — that is a
pipeline-wide question, not a regex_5354 one, and it may surface more findings across
the whole corpus.

---

## Suggested next steps

1. **Is it known?** Search the bun issue tracker and WebKit Bugzilla (Yarr) for
   `^` / anchor hoisting / `multiline`. Determine whether to report upstream, and
   whether it is fixed after 1.3.14 (the pins are deliberate — do **not** bump the
   image to check; test a newer bun out-of-band).
2. **Is it bun or JSC?** Run the probe against a standalone `jsc` binary. If plain JSC
   reproduces it, this is a WebKit bug and should be filed there, not against bun.
3. **Narrow the trigger.** Does it need a *group*, or does a bare `(?:^)?` do it? Does
   `y` at index 0 always work? Does `sticky`/`y` interact? Does `$` have a mirror bug
   (a `$` in a zero-matchable group refusing matches before the end)? — a `$` probe is
   the obvious symmetric test and is not yet run.
4. **Quantify the blast radius.** Re-fuzz `exec`/`test`/`replace`/`split` for
   regex_5354 with a padded input and see if they diverge too. If they do, that is an
   argument for a pipeline change.
5. **Catalogue it** as F002 in `DISCREPANCIES.md`, following the F001 entry: index-table
   row, run provenance, engine-split table, evidence folder. The evidence folder is
   already populated.

## Re-running things

Evidence folder `regex_5354__bun_anchor_hoist/` contains `probe.js`, `probe_output.txt`,
`matchAll.diff.json` (all 80 cases), the exact reproducer harness `matchAll__0__g.js`,
plus `base.fan` / `matchAll.fan` / `matchAll.strings.jsonl`.

> **Image tags changed on 2026-07-14.** `verbal:latest` is no longer 48defb5 — it was
> rebuilt for the 6000–9999 run and now bakes `cccf63e`. The image the 4000–5999
> artifacts were produced by is preserved as **`verbal:48defb5`** (it was briefly only a
> dangling image, one `docker image prune` from being lost). Use that tag for anything
> that must match this window's provenance; `verbal:cccf63e` is the new build.

```bash
# the PoC, on the pinned engines (engines are identical in both tags, so either works)
cd ~/projects/verbal
D=analysis/differential_findings/regex_5354__bun_anchor_hoist
for e in "node" "bun" "deno run --quiet"; do
  docker run --rm --entrypoint sh -v "$PWD/$D:/probe:ro" verbal:48defb5 -c "$e /probe/poc.js"
done
# -> node: 6/6 pass | deno: 6/6 pass | bun: 4/6 FAIL

# the single original reproducer (from the real corpus run)
docker run --rm --entrypoint sh -v "$PWD/$D:/probe:ro" verbal:48defb5 -c "bun /probe/matchAll__0__g.js"

# re-evaluating anything in results-run-4000-5999/ MUST use verbal:48defb5 --
# verbal:latest would stamp a different eval commit and invalidate diff reuse.
```

## Session state you should know about

- **The recovery eval is finished** (2026-07-14, log
  `results-run-4000-5999/eval_recovery_4000_6000.log`). It evaluated rows 4000–5064,
  whose tests never ran because the original run was killed mid-generation at
  regex_5064. `results-run-4000-5999/eval_headline.json` now covers the **whole**
  4000–5999 window: `complete: true`, 1,871 ok regexes, 9,355/9,355 units, 484,588
  cases, **40 value discrepancies, 0 defects**. Chunk-2's original headline is backed up
  beside it as `eval_headline.chunk2-5065-5999.json.bak` (it described only 5065–5999).
- **Chunk-1 (rows 4000–5064) added no new discrepancies.** Its 996 regexes / 4,980 units
  / ~257k cases came back completely clean, so **regex_5354 remains the only discrepant
  regex in the entire window** — this handoff is the whole story for rows 4000–5999.
  All 1,871 diffs carry the same eval commit `48defb5`, so the window has uniform
  provenance.
- **Those changes are now committed** (`5845476`, `e8da4a2`, `cccf63e` on `repo-reorg`):
  per-window `run_record_<start>_<end>.json` / `eval_headline_<start>_<end>.json`, the
  `artifacts_to_run_record.py` recovery tool, and `START`/`PY` knobs for the chunked
  drivers. The 4000–5999 recovery eval deliberately ran on the **old** `48defb5` code so
  the whole window carries one provenance — that is why its headline is still the
  fixed-name `eval_headline.json` rather than the new per-window name.
- Never bake a `GIT_COMMIT` that isn't the real source commit; `docker/build.sh` appends
  `-dirty` for a dirty tree, which is correct but is not something a reader can
  reconstruct — commit first.
- `regex_5064` is excluded from the record as `torn_artifact` (0-byte
  `matchAll.strings.jsonl` from the kill). Checked on 2026-07-14 by regenerating it in
  isolation: it is **`ok`, not skipped** — it generates all 5 APIs and evaluates to 400
  cases with **0 discrepancies, 0 defects**. So excluding it costs no signal, and it is
  deliberately left out rather than merged (its artifacts would be standalone-generated
  while the rest of the window was generated in-sequence).

- ✅ **RESOLVED 2026-07-15 — the check passed; F002 is unblocked.** The question below
  is answered: **the artifacts are reproducible; the regeneration recipe was wrong.**

  `regex_5354` reproduces **byte-for-byte — all 411 files** (400 harnesses, 5
  `strings.jsonl`, 6 `.fan`) on the pinned `verbal:48defb5`, once generated the way it
  actually was. `overnight_drive.sh` runs `overnight_run.py` **one fresh process per
  100-row chunk**, so `regex_5354` was made in chunk `--start 5300 --count 100` with
  **54 preceding rows in its process** — and `48defb5`'s generation depends on that
  in-process history. `--start 5354 --limit 1` gives the row a history it never had,
  which is why it produced different strings. Rows after 5354 cannot affect it, so the
  reproduction is:

  ```bash
  # regenerate a PRE-3ab1fc3 row: it needs its CHUNK, not the row alone.
  #   chunk start = floor(id/100)*100 ; count = 100 (or just enough to cover the row)
  docker run --rm --entrypoint sh verbal:48defb5 -c "cd /app && python - <<'PY'
  import sys; sys.path.insert(0, '/app/src')
  from pipeline.config import load_config, seed_everything
  from pipeline.run import load_corpus, process_row_range
  import paths
  cfg = load_config('/app/config/fullcorpus.yaml'); seed_everything(cfg)
  paths.ensure_results_dirs()
  process_row_range(load_corpus(cfg)[5300:5355], 5300, cfg)
  PY"
  # -> results/regex_5354/ matches results-run-4000-5999/regex_5354/ byte-for-byte
  ```

  **The hypothesis below was right on both counts.** The position dependence is real,
  and `3ab1fc3` fixes it — verified by running the same chunk on both images:

  | image | isolated (0 preceding) | in-chunk (54 preceding) | position-dependent? |
  |-------|------------------------|-------------------------|---------------------|
  | `48defb5` | `445809212a4fa596` | `391895d5df49cd18` | **yes** |
  | `d1f3125` (HEAD) | `445809212a4fa596` | `445809212a4fa596` | **no** — fixed |

  **Correction to the text below:** `regex_5064` did **not** have 1,064 preceding
  rows. Chunking means it had ~64 (chunk 5000–5099), and `regex_5354` had ~54. That
  mis-estimate is likely why "one preceding row → identical" read as exculpatory: the
  real gap was ~54 rows, not ~1,064, so one row was a far weaker probe than it looked.
  `regex_5064` was itself "checked by regenerating it in isolation" (see above) — the
  same wrong recipe, which is why it looked broken too.

  **What remains** is small and does not affect any finding: for pre-`3ab1fc3`
  artifacts the recorded provenance (commit/`config_sha`/seed/corpus) omits the chunk
  context, so a reader needs the recipe above. HEAD is position-independent, so future
  artifacts reproduce from provenance alone. Tracked in
  [`../EXPERIMENT_GAPS.md`](../EXPERIMENT_GAPS.md#g6-remaining).

  <details>
  <summary>Original open question (kept for the record — superseded by the above)</summary>

  ⚠️ **Open reproducibility question — check this before writing up F002.**
  regex_5064's *original* artifacts cannot be reproduced by the pinned image:
  `exec.strings.jsonl` is 7012 bytes on disk, but the image reproducibly regenerates
  4272 — with byte-identical `base.fan` and `exec.fan`, identical `count: 20`, and
  identical provenance (`48defb5` / `d769e16a…` / seed 0 / same corpus). Ruled out by
  experiment: run-to-run nondeterminism (same command twice → identical), wall-clock
  load (`--cpus=0.35`, 3× slower → identical), one preceding row (→ identical), a
  later image build (image created 00:04:35, artifacts 08:15), and config/seed/corpus
  drift. `regex_5065` by contrast reproduces byte-for-byte (400/400 harnesses), so this
  is not broad nondeterminism.

  Unproven lead: the **baked `48defb5`** `_fuzz` (in-process `signal.alarm`, which is
  what actually ran — HEAD's `3ab1fc3` replaced it with a forked child that calls
  `random.seed(seed)`) runs its estimate probe
  `fdo.fuzz(desired_solutions=100, max_generations=1)` **unseeded** on the shared `fdo`
  object, passing `random_seed` only to the second call. That could make output depend
  on how many rows preceded it in the process (the original had 1,064; one preceding row
  was not enough to reproduce the effect). If true, `3ab1fc3` already fixes it.

  **Why it matters here:** if artifacts are not reproducible from recorded provenance
  alone, then provenance is incomplete, and a reader cannot regenerate the exact inputs
  behind a finding. **Spot-check regex_5354's own artifacts the same way** — regenerate
  `--start 5354 --limit 1` and compare to `results-run-4000-5999/regex_5354/` — before
  publishing F002. The *finding* does not depend on it (the engine disagreement is real
  on the inputs as they exist, and the minimal `/(?:^x)*?y/g` reproducer is independent
  of the pipeline entirely), but the reproducibility claim around it does.

  </details>
