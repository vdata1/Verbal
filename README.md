# Verbal

Verbal is a differential-testing framework for JavaScript regular-expression engines: given a
regex, it builds a Fandango grammar that generates matching strings, specializes it, emits JS
test harnesses, and runs them across **node / bun / deno** to find discrepancies.

**It has found bugs.** Five are catalogued as confirmed findings and seven have file-ready
upstream reports. Start at [`analysis/bug_reports/FILING_PLAN.md`](analysis/bug_reports/FILING_PLAN.md).

---



> **On a server that gives you LXC rather than Docker?** Go to
> [`RUN_ON_LXC.md`](RUN_ON_LXC.md) instead — it is a standalone native path (no image, no
> nesting) and covers §1–§3 below in LXC terms. Come back here for the knob reference.

### 1. Confirm the setup works

Two options, depending on how much time you want to spend.

**(a) Fast plumbing check — 3 seconds.** Runs all four pipeline stages on the tiny sample corpus
in an isolated temp dir that never touches `results/`, and prints
`SMOKE PASS: all four pipeline stages produced output`:

```bash
docker run --rm -v "$PWD":/app --entrypoint bash verbal:latest \
  -lc 'PYTHON=python3 tests/smoke_test.sh'
```

`PYTHON=python3` is required: the script defaults to the repo venv at `./bin/python`, which does
not exist inside the image, and without it you get `/app/bin/python: No such file or directory`.
(On a host with the venv set up, plain `tests/smoke_test.sh` works.)

**(b) Full-stack check — ~30 minutes, 10 real corpus regexes.** This is the one that proves the
Docker image, the engine pins, both phases and the artifact layout all work:

```bash
docker build -t verbal:latest .            # first time only; see DOCKER_GUIDE.md

RESULTS_SMOKE=/path/to/an/empty/dir       # anywhere you own, outside the repo

docker run -d --name verbal_smoke --memory 8g --memory-swap 8g \
  -v "$PWD":/app -v "$RESULTS_SMOKE":/app/results \
  --entrypoint bash verbal:latest -lc '
    START=0 TOTAL=10 WINDOWS=1 CHUNK=10 GEN_BUDGET=900 WORKERS=4 \
    CONFIG=config/fullcorpus.yaml PY=python3 OUTDIR=results/smoke \
    analysis/eval_help_scripts/scoped_run.sh'

docker logs -f verbal_smoke      # progress; detached so a dropped shell cannot kill it
```

Verified 2026-08-03: exits 0 in **30m18s** (Phase A generation 22.5 min, Phase B eval 473 s),
producing 16,839 cases. Expect:

```
smoke_test/eval_headline_0_10.json    "complete": true, 0 value discrepancies
smoke_test/run_record_0_10.json       10 outcomes: 9 ok, 1 skipped_non_regex
smoke_test/redos_0_10.json            0 candidates
smoke_test/regex_1/ ... regex_9/      per-regex harnesses + <api>.diff.json
smoke_test/smoke/                     drive_0.log, summary.json, chunk_000000.json
```

```bash
python3 -c "import json;d=json.load(open('$RESULTS_SMOKE/eval_headline_0_10.json'));print(d['complete'], d['totals'])"
```

**Zero discrepancies is a PASS, not a failure** — ten regexes off the front of the corpus are
unremarkable. The point is that both phases complete and the artifacts appear. Likewise
`1 skipped_non_regex` is expected: corpus row 0 has `pattern: false`.

Two things that will confuse you if you don't know them:

- **`WORKERS` only affects Phase B.** Phase A generation is driven by `WINDOWS`, so with
  `WINDOWS=1` generation runs on roughly one core no matter what `WORKERS` says.
- **Artifacts land at the mount root, not in `OUTDIR`.** `OUTDIR` holds only the driver's own
  logs and chunk records; headlines, run records and `regex_*/` go to `/app/results` directly.

### 2. Running a real experiment

The single entry point is `analysis/eval_help_scripts/scoped_run.sh`, which does **Phase A**
(N-way parallel chunked generation) then **Phase B** (`run_eval.py --skip-generate --resume`).
This is how every recorded result was produced.

```bash
RESULTS=/path/to/your/results        # somewhere with tens of GB free
START=20000 TOTAL=3000               # corpus rows [START, START+TOTAL)
NAME=run_$START

docker run -d --name verbal_$NAME \
  --memory 32g --memory-swap 32g \
  -v "$PWD":/app -v "$RESULTS":/app/results \
  --entrypoint bash verbal:latest -lc "
    mkdir -p results/$NAME &&
    START=$START TOTAL=$TOTAL WINDOWS=8 CHUNK=100 GEN_BUDGET=36000 WORKERS=8 \
    REDOS_DEFER=1 CONFIG=config/fullcorpus.yaml PY=python3 OUTDIR=results/$NAME \
    analysis/eval_help_scripts/scoped_run.sh > results/$NAME/scoped_run.log 2>&1"
```

`WINDOWS=8`/`WORKERS=8`/`--memory 32g` are placeholders — size them to your machine using the
tables below.

#### `scoped_run.sh` settings

| Variable | Meaning | How to choose |
|---|---|---|
| `START` | first corpus row (0-based index into `data/uniq-regexes-8.json`) | see §3 |
| `TOTAL` | how many rows to cover, i.e. rows `[START, START+TOTAL)` | 3000 is a comfortable window |
| `WINDOWS` | **Phase A parallelism.** Splits the range into N disjoint sub-windows, one generation driver each | ≈ the cores you're willing to occupy. This is the knob that decides how long generation takes |
| `WORKERS` | **Phase B parallelism.** Thread pool for the differential eval | ≈ cores. Has no effect on Phase A |
| `CHUNK` | rows per chunk within a driver; a chunk is the resume unit | 100 is fine; smaller = finer-grained resume, more overhead |
| `GEN_BUDGET` | wall-clock seconds allowed **per generation driver** | generous — generation is the slow phase. It is a stop condition, not a target |
| `REDOS_DEFER` | `1` = write `redos_queue_<window>.json` (nominations only); `0` = confirm inline | **use `1`.** Inline confirm was ~40% of a run's wall-clock, and timings taken under pool load are inflated and not findings |
| `CONFIG` | run config | `config/fullcorpus.yaml` for real runs |
| `OUTDIR` | where the **driver's own** logs/chunk records go, relative to `/app` | anything per-run, e.g. `results/run_20000` |
| `PY` | python interpreter inside the image | `python3` |

#### `docker run` flags

| Flag | Why |
|---|---|
| `-d` | detached. A foreground run dies with your shell; this survives a dropped connection |
| `--name` | so you can `docker logs` / `docker stop` it deterministically later |
| `--memory` / `--memory-swap` | **set both, equal.** Caps the container instead of letting it take the machine down. Check whether your host has swap (`free -h`); with swap disabled an unbounded container OOM-kills the *host*, not itself |
| `-v "$PWD":/app` | the repo. Provenance is stamped from `git status --porcelain`, so avoid editing tracked files mid-run |
| `-v "$RESULTS":/app/results` | where artifacts land. Keep it off the repo and distinct from anyone else's run |
| `--cpuset-cpus a-b` | *optional.* Pin to specific cores if you're sharing the machine, so your run and someone else's don't fight |

#### Things that will bite you

- **The `mkdir -p` is load-bearing.** The shell opens the `>` redirect *before* `scoped_run.sh`
  runs, so without it the container dies instantly with "No such file or directory" and
  `docker logs` shows nothing useful.
- **Watch `$OUTDIR/scoped_run.log`, not `docker logs`** — the driver redirects there, so
  `docker logs` stays empty for hours and looks hung when it isn't.
- **Artifacts land at the results mount root**, not in `OUTDIR`; `OUTDIR` holds only driver logs
  and chunk records.
- **Phase A is resumable**, so killing a run after generation is cheap — re-invoking reuses the
  harnesses and only Phase B re-runs. But Phase B's `--resume` reuses a `<rid>/<api>.diff.json`
  **only** when resolved config, git commit and engine versions all match, so don't change HEAD
  mid-run: everything already computed becomes unreusable.
- **Sizing intuition.** Generation dominates and parallelises across `WINDOWS`; the eval phase is
  comparatively quick. For reference, on the 48-core machine these results came from, 10 regexes
  at `WINDOWS=1` took ~30 min end-to-end (22.5 min of it generation), and a 3000-row window at
  `WINDOWS=30` finished Phase A in about 6 hours. Scale from your own core count rather than
  copying those numbers.

### 3. Which range to run

**Suggested: `START=25000 TOTAL=3000`.**

Corpus `data/uniq-regexes-8.json` has **537,805** regexes, so there is plenty of room. Ranges
already used here are **0–20035** (0–3, 4000–5999, 6000–10050, 10050–12050, 12050–15050, and
15050–20035, the last of which was still evaluating as of 2026-08-04).

**Note the 20035.** A window's final chunk can over-read past its nominal end: the 15050–20000
run splits into 30 sub-windows of 165 rows, so its last driver starts at 19835 and its final
`CHUNK=100` chunk runs to 20035 — which is why that window's headline is
`eval_headline_15050_20035.json` and not `..._20000.json`. Check the actual headline filenames
rather than the `START`/`TOTAL` a run was launched with. Starting at 25000 leaves a clear
buffer above everything touched, so nothing you produce will collide with or be confused for
our artifacts.

Point your results mount at your own directory and give `OUTDIR` a per-run name, so two runs can
never interleave in one results tree. Nothing about the range depends on which machine you use —
only the corpus, which is tracked in the repo and identical everywhere.

---

## Findings

| Where | What |
|---|---|
| [`analysis/bug_reports/`](analysis/bug_reports/) | Seven file-ready upstream report drafts + [`FILING_PLAN.md`](analysis/bug_reports/FILING_PLAN.md) (venue, claim strength, open items). **Nothing has been filed yet.** |
| [`analysis/differential_findings/DISCREPANCIES.md`](analysis/differential_findings/DISCREPANCIES.md) | F001–F005, the confirmed cross-engine value discrepancies, each with an evidence folder |
| [`analysis/potential_findings/CANDIDATES.md`](analysis/potential_findings/CANDIDATES.md) | Untriaged candidates staged for promotion or rejection |
| [`analysis/EXPERIMENT_GAPS.md`](analysis/EXPERIMENT_GAPS.md) | G1–G9: ways a real bug can exist and never appear in a headline |
| [`analysis/redos_nomination/`](analysis/redos_nomination/) | ReDoS nomination method, plus the window 12050–15050 triage |

Three of the bun findings are **Yarr JIT miscompiles** — they disappear under
`BUN_JSC_useRegExpJIT=0`, which settles ground truth without any cross-engine vote.

## Engines

For parity with the recorded results you must use these **exact** versions. Mismatched engines
make results non-reproducible, and the Docker image pins and verifies them at container start.

| Engine | Version | Notes |
|---|---|---|
| node | v26.5.0 | V8 |
| bun | 1.3.14 | JavaScriptCore (Zig build) — the pinned target |
| deno | 2.9.1 | V8; platform triple in the banner differs per OS/arch |
| **bun canary** | **1.4.0-canary.1+52af83272** | **the Rust rewrite** of Bun (merged May 2026). Linux x64 glibc only. **Optional fourth target.** |

### The bun Rust-rewrite canary

Bun was rewritten from Zig to Rust in 2026; the rewrite ships on the canary channel. It is worth
testing against because it is the first substantial change to Bun's own runtime layer in a long
time — but note the result we already have:

> **All five findings reproduce on the canary byte-for-byte identically to 1.3.14**, and the
> JIT tier differential holds there too (17/59 probe cases wrong with the JIT, 0/59 without).

That is the expected outcome — the rewrite replaced Bun's own code, not JavaScriptCore — and it
is useful evidence: it argues the defects live in **JSC/Yarr**, so WebKit is likely the right
venue rather than oven-sh/bun.

Fetch it (not tracked in the repo; it is a 34 MB binary):

```bash
ENGINES=/path/to/engines
mkdir -p "$ENGINES" && cd "$ENGINES"
curl -sSL -o bun-canary.zip \
  https://github.com/oven-sh/bun/releases/download/canary/bun-linux-x64.zip
unzip -oq bun-canary.zip && chmod +x bun-linux-x64/bun
```

Run any probe against it by mounting the directory into the image:

```bash
docker run --rm -v "$ENGINES":/eng:ro \
  -v "$PROBES":/probe:ro \
  --entrypoint bash verbal:latest -lc '/eng/bun-linux-x64/bun /probe/probe_vclass_generalize.js'
```

**It is deliberately not wired into `ENGINE_CMD`.** The pinned three are what every recorded
artifact was produced with, and adding a fourth engine would change provenance for every result.
Use it as a side-by-side check. If you do want it as a first-class target, the intended extension
point is `ENGINE_ENV` / `analysis/eval_help_scripts/tier_diff.py`, which registers variants as
pseudo-engines so existing code paths apply unchanged.

## Repository layout

```
src/        pipeline code + unit_test_templates/ + paths.py (central path config)
eval/       run_eval.py -- the differential eval driver (Phase B)
config/     run configs; fullcorpus.yaml is the one used for real runs
data/       input regex corpora (tracked): uniq-regexes-8.json, sample, harvest
docker/     entrypoint + engine pinning
analysis/   findings, bug reports, experiment gaps, handoffs, eval helper scripts
tests/      regex/fandango spec collections + smoke_test.sh
archive/    superseded prototype code (kept for provenance)
```

All filesystem locations are defined in `src/paths.py` and resolved from the project root, so the
pipeline can be launched from anywhere.

> **`results/` is not in the repo.** It is a bind-mount, supplied at `docker run` time and
> mounted at `/app/results`; nothing in `results/` is tracked. On the machine these findings came
> from it lives at `/scratch/turcotte/verbal` (see `WHERE_ARE_RESULTS.md`) — put yours wherever
> you like. Headlines are **per window** — `eval_headline_<start>_<end>.json`, not a single
> `eval_headline.json`.

> **`*.md` is gitignored wholesale.** Docs are force-added (`git add -f`). Two consequences:
> `grep`/`ripgrep` silently skip every markdown file unless you bypass the ignore
> (`find . -name '*.md' -print0 | xargs -0 grep -n ...`), and a handful of docs *are* tracked, so
> editing them dirties the tree — which taints `config._git_commit` for any run in flight. Check
> with `git ls-files analysis/ | grep '\.md$'` before editing docs during a run.

## Setup (without Docker)

Docker is the recommended path because it enforces the engine pins. If you need a local env:

```bash
git clone https://projects.cispa.saarland/c01abal/verbal.git
cd verbal
python -m venv . && source ./bin/activate
pip install pandas numpy matplotlib
```

Verbal relies on a lightly modified Fandango (customizable tree search, explicit surrogate
handling on en/decode):

```bash
git clone https://github.com/reallyTG/fandango-slight-change.git fandango
cd fandango && python -m pip install -e .
```

(Note the explicit target directory — the repo name and the expected directory name differ.)

You will also need node/bun/deno at the exact versions in the table above, on `PATH`.

## Older single-regex entry point

`src/main.py` still drives generation directly and is useful for poking at one regex:

```bash
python src/main.py -g -n 2 -r ./data/uniq-regexes-sample.json -f -fn 50 -u -un 20 -d -dn 20
```

- `-g` generate grammars; `-n 2` two mutated grammars each
- `-r` path to the regex corpus
- `-f -fn 50` fuzz the grammars, 50 inputs each
- `-u -un 20` generate unit tests (a lenient bound; typically more are produced)
- `-d -dn 20` run 20 unit tests

`-fn`/`-un`/`-dn` exist to control combinatorial explosion. **For real experiments use
`scoped_run.sh`** — it is what produced every recorded result, and it handles parallel
generation, resume, and the ReDoS split.

## Docker

See [`DOCKER_GUIDE.md`](DOCKER_GUIDE.md).
