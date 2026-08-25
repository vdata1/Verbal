# Docker Setup Guide for Verbal

Runs the Verbal pipeline (generation + differential eval) in a single reproducible
image. **One container holds all three JS engines**; Python spawns `node`/`bun`/`deno`
as in-process subprocesses (see `eval/run_eval.py`), so there is *no* per-call
container overhead. A full eval is ~1M short-lived engine spawns — a container per
engine, or `docker run` per call, would be catastrophically slow and is deliberately
not how this is set up.

## Why Docker here

- **Blast-radius containment.** The stack needs a Python venv, a forked Fandango, and
  three JS runtimes at specific versions. The image quarantines all of it from the
  host; `docker rmi` is the whole cleanup.
- **Reproducibility.** Engine versions are **pinned** to exactly what produced the
  recorded results (the per-window `results/eval_headline_<start>_<end>.json`):
  **node v26.5.0, bun 1.3.14, deno 2.9.1**.
  They are installed from official release artifacts by exact version
  and **verified at every container start** (`docker/entrypoint.sh` →
  `docker/assert_engine_versions.py`); a drift aborts the run rather than silently
  producing non-reproducible numbers. This closes the previous gap where the runner
  used whatever `node` was first on `PATH`.

## Prerequisite: clone the forked Fandango

Verbal depends on a lightly-modified Fandango (customizable tree search + explicit
surrogate passing on en/decode). It is **not** a git submodule (so you can fork it
and make local changes freely). Before building, clone it into `./fandango`:

```bash
git clone https://github.com/reallyTG/fandango-slight-change.git fandango
```

The Docker build `COPY`s whatever is in `./fandango` and installs it **non-editable**
(the fork uses scikit-build-core, whose editable mode needs extra config and buys
nothing in an image where the code is fixed at build time). Local changes you make
there are still picked up — on the next `docker compose build`.

## Build

```bash
docker compose build
```

To re-pin engine versions deliberately, either edit the `ARG` defaults in the
`Dockerfile` or pass build args (see the commented block in `docker-compose.yml`):

```bash
docker compose build --build-arg NODE_VERSION=26.5.0 \
  --build-arg BUN_VERSION=1.3.14 --build-arg DENO_VERSION=2.9.1
```

## Run

The entrypoint asserts engine pins first (prints `engine pins OK: ...`), then runs
your command.

```bash
# Interactive shell
docker compose run --rm verbal bash

# Generation pipeline (from /app; paths.py resolves the layout CWD-independently)
docker compose run --rm verbal python src/main.py \
  -g -n 2 -r ./data/uniq-regexes-8.json -f -fn 50 -u -un 20 -d -dn 20

# Differential eval (parallel + resumable; set workers to your allotted cores)
docker compose run --rm verbal python eval/run_eval.py --workers 12 --resume

# End-to-end smoke test (tiny fixtures, isolated temp dir)
docker compose run --rm verbal env PYTHON=python3 tests/smoke_test.sh
```

`PYTHON=python3` is **required**: `smoke_test.sh` defaults to the repo venv at
`./bin/python`, which does not exist inside the image, and without it you get
`/app/bin/python: No such file or directory`.

Bare `docker run` also works (data/ is baked into the image):

```bash
docker build -t verbal:latest .
docker run --rm -it \
  -v "$(pwd)/results:/app/results" \
  -v "$(pwd)/results-archive:/app/results-archive" \
  verbal:latest python eval/run_eval.py --workers 12 --resume
```

### Real experiments need the repo mounted

The commands above are for poking at the image. **Every recorded result was produced
by `analysis/eval_help_scripts/scoped_run.sh`, which is _not in the image_** —
`.dockerignore` excludes `analysis/` wholesale. It only exists in the container when
you bind-mount the repo over `/app`:

```bash
-v "$PWD":/app
```

That mount is also what makes `git rev-parse` see the tree actually being executed.
For the real-run recipe — detached (`-d`), memory-capped (`--memory` **and**
`--memory-swap`, equal), optionally core-pinned — see
[the README](README.md#2-running-a-real-experiment). Do not run a 15–30h window in the
foreground, and do not run one uncapped on a host with swap disabled.

## Volumes

| Container path | Host path | Purpose |
|---|---|---|
| `/app/results` | `./results` | All pipeline outputs (huge, regenerable — mounted, never baked). **For real runs point this somewhere off the repo** — budget ~65 GB and ~7M files per 3000-row window (see Performance notes) — and give each run its own `OUTDIR` — see [the README](README.md#docker-run-flags) |
| `/app/results-archive` | `./results-archive` | Dated experiment snapshots |
| `/app/data` (ro) | `./data` | Input corpora — swap without rebuilding (also baked in) |

## Performance notes

- **In-container subprocess spawns are native.** On a Linux server, running inside
  the container adds no measurable overhead versus bare metal for the ~1M engine
  spawns; the eval stays startup-bound exactly as before.
- **Match `--workers` to allotted cores.** `run_eval.py` defaults to host CPU count;
  inside a CPU-limited container, pass `--workers N` explicitly so it doesn't
  oversubscribe.
- **Filesystem is the one real cost, and it is larger than it looks.** Measured over
  15 regexes of a live window: ~2535 harness `.js` files and ~23.7 MB **per regex**, so
  a 3000-row window (~2800 regexes) runs to roughly **65 GB over ~7 million files**.
  The accumulated tree for rows 0–20035 is 214 GB over 30.4M files. Two consequences:
  **check `df -i`, not just `df -h`** — 7M files exhausts a default `mkfs.ext4` volume
  (one inode per 16 KB) before it runs out of space, giving you
  `No space left on device` with tens of GB free — and avoid a slow bind mount (or
  Docker Desktop's Mac VM bridge) for `results/` if you care about wall-clock.

## Transferring to a server

Ship code, not outputs. `.dockerignore` already keeps `results/` (14G),
`results-archive/` (7.7G), and the local venv out of the build context.

```bash
git clone https://projects.cispa.saarland/c01abal/verbal.git
cd verbal
git clone https://github.com/reallyTG/fandango-slight-change.git fandango
docker compose build
docker compose run --rm verbal env PYTHON=python3 tests/smoke_test.sh   # sanity check
```

**On a server that gives you LXC rather than Docker**, skip all of this and see
[`RUN_ON_LXC.md`](RUN_ON_LXC.md) — nothing in the pipeline actually requires Docker,
and nesting it inside LXC buys nothing.

## Troubleshooting

- **`no pins file at /app/.engine-pins.json` on startup** — you mounted the repo
  (`-v "$PWD":/app`) and your checkout has no `.engine-pins.json`. The mount replaces
  `/app` wholesale, shadowing the copy the Dockerfile baked in; the file is untracked
  (it is in `.git/info/exclude`), so a **fresh clone does not have one**. This is the
  same shadowing that broke `.git-commit` and cost the 6000–10050 window its
  provenance. Recreate it at the repo root:

  ```bash
  printf '{"node":"26.5.0","bun":"1.3.14","deno":"2.9.1"}\n' > .engine-pins.json
  ```

- **Engine version mismatch on startup** — the assert is doing its job: the engines on
  `PATH` are not the pinned ones. Inside an unmounted image that means the build used
  different `ARG`s — rebuild (`docker compose build`), or re-pin deliberately. Note the
  image *generates* `.engine-pins.json` from those same ARGs, so an unmounted image
  cannot disagree with itself; if you see this, suspect a mount.
- **Permission errors on mounted `results/`** — the container runs as root, so
  host-side files land root-owned. `chown` them back, or run the container with
  `--user "$(id -u):$(id -g)"`.
- **`COPY fandango` fails** — you skipped the clone prerequisite above.
