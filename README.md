# Verbal

Verbal is a differential-testing framework for JavaScript regular-expression
engines. Given a regex it builds a [Fandango](https://github.com/fandango-fuzzer/fandango)
grammar that generates matching strings, specializes that grammar per JS regex
API, emits JS test harnesses, and runs them across **node / bun / deno** looking
for discrepancies.

Twelve cross-engine defects are documented, each with a self-contained reproducer
in [`pocs/`](pocs/README.md). Those need no setup beyond the engines themselves —
no Python, no Fandango — so they can be run before anything below:

```bash
bun pocs/f002_bun_anchor_hoist_zero_matchable_group.js
```

## Setup

Python >= 3.11, plus node, bun and deno. The engine versions are part of the
experiment: results are only comparable against **node v26.5.0, bun 1.3.14,
deno 2.9.1**.

### Docker (recommended)

The image installs exactly those versions and verifies them at container start,
so a version drift aborts the run rather than silently producing numbers that
cannot be compared. It also clones and patches Fandango for you.

```bash
./docker/build.sh
```

### Without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Fandango, at the pinned commit, with this project's two additions applied.
git clone https://github.com/fandango-fuzzer/fandango.git fandango
git -C fandango checkout 01be7a03de16f3dfbd95fb1596884245b5f333e3
git -C fandango apply ../patches/fandango-verbal.patch
pip install ./fandango
```

The patch is 21 lines across two files: a `stop_at`/`bfs_mode` option on
`DerivationTree.find_subtrees`, and `errors="surrogatepass"` on the tree-value
encode/decode path so lone surrogates survive a round trip.

Outside Docker the engines are plain `PATH` lookups and are not checked, so a
bare-metal run has to put the right versions first on `PATH` itself.

### Check it works

```bash
tests/smoke.sh
```

Runs both entry-point modes end-to-end in an isolated temp directory and asserts
every stage produced output. It never touches `results/`.

## Quick start

Two commands. On a laptop the first takes about 15 seconds, the second about a
minute.

```bash
python verbal.py --regex '(?:^x)*?y'   # one regex
python verbal.py --limit 5             # the first 5 regexes of the paper corpus
```

Under Docker, mount only `results/` so the artifacts land on the host:

```bash
docker run --rm -v "$PWD/results":/app/results \
    verbal:latest python verbal.py --regex '(?:^x)*?y'
```

Do not mount over `/app` itself — that shadows the baked-in engine pins and the
version assert fails at container start.

The single-regex example is worth running first: it rediscovers one of the
reported defects from scratch. `(?:^x)*?y` has an anchor inside a group that can
match zero times, and bun's JIT hoists the `^` out, so bun reports no matches
where node and deno find three. The run ends with a summary and pointers to the
per-API diff artifacts:

```
window     0..1
complete   True
cases                     96
defect_cases              0
timeout_cases             0
value_discrepancies       82

82 value discrepancy/ies:
  regex_0 exec #0 [none]  -> results/regex_0/exec.diff.json
  ...
```

`--limit 5` finds no discrepancies, which is the normal result: five regexes off
the front of the corpus are unremarkable. Zero discrepancies is a successful run,
not a failed one.

## Running on the paper corpus

`data/paper_eval_set_patterns.json` holds the **15,931 patterns** the reported
results were computed over, as a JSON array of pattern strings. Its order is the
order they were evaluated in.

```bash
python verbal.py --config config/paper.yaml --start 0 --limit 100
```

`--start`/`--limit` select the corpus window `[start, start+limit)`. Regex ids
are `regex_<position in the corpus file>` and are stable across windowings, so
windows can be run independently and in any order without colliding.

Two configs are provided:

| Config | For |
|---|---|
| `config/minimal.yaml` | the quick start. Small generation budget, two flag variants. Not for producing numbers. |
| `config/paper.yaml` | the reported results. Full eight-way flag matrix, full generation budget. |

Generation dominates the wall clock, and cost per regex varies by orders of
magnitude with pattern complexity. Start with a small `--limit` and scale up.

The corpus loader accepts either a JSON array of pattern strings, as above, or
JSON Lines with a `pattern` field per row, so another regex corpus can be
substituted by pointing `corpus` in the config at it.

## Output

Everything lands under `results/`, joinable by regex id:

```
results/<regex_id>/base.fan                 the mutation-free grammar
results/<regex_id>/<api>.fan                specialized for one JS API
results/<regex_id>/<api>.strings.jsonl      generated strings, with origin
results/<regex_id>/<api>__<n>__<flags>.js   one harness per (string, flag set)
results/<regex_id>/<api>.diff.json          per-engine results and the diff
results/run_record_<start>_<end>.json       per-regex generation outcomes
results/eval_headline_<start>_<end>.json    totals and the discrepancy index
```

Records and headlines are named for the window they cover, so windows never
overwrite each other and no file can describe rows it did not evaluate.

A **value discrepancy** is the finding of interest: every engine ran cleanly and
returned a *different result*. Crashes and timeouts are tracked separately as run
defects and are not discrepancies.

Every regex gets a recorded outcome — `ok`, `not_js`, `unsatisfiable`,
`no_inputs`, `error`, and others — so nothing is silently dropped from a count.
The full taxonomy is documented at the top of `src/pipeline/run.py`.

Each artifact carries a provenance header recording the git commit, the resolved
config hash, the seed, the corpus hash, and the engine versions, so a result can
be traced to the exact code and data that produced it.

## ReDoS candidates

A case whose in-harness execution time exceeds `redos_slow_ms` on any engine, or
which times out, is nominated as a ReDoS candidate. Nominations are measured
inside the parallel worker pool, where load inflates timings, so they are not
findings on their own. They are re-executed serially and unloaded, and kept only
if still slow.

`--redos-defer` writes the nominations to `results/redos_queue_<window>.json`
without measuring them, so the confirm phase can run later on a quiet machine:

```bash
python eval/run_eval.py --config config/paper.yaml --limit 100 --redos-defer
python eval/confirm_redos.py --queue results/redos_queue_0_100.json
```

Each queue entry carries its own harness source, so the queue file is sufficient
input and no `results/` tree needs to travel with it. A confirmed case is
engine-specific slowness, not proven superlinear blowup: nothing here varies
input length, which is what a catastrophic-backtracking claim would require.

## Layout

```
verbal.py     entry point: one regex, or a corpus window
src/          the pipeline; paths.py holds the filesystem layout
eval/         the differential eval driver
config/       run configurations
data/         the paper corpus
patches/      the Fandango patch
pocs/         minimal reproducers for the reported bugs
docker/       engine pinning and the runtime version assert
tests/        end-to-end smoke test
```
