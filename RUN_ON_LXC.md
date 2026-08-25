# Running Verbal in an LXC container

Native setup, no Docker. Don't nest Docker inside LXC — an LXC container is a full userspace,
so the pinned engines install directly.

For what to run and what the knobs mean, see [`README.md`](README.md). This file is setup only.

## Prerequisites

| | |
|---|---|
| **Base image** | **Ubuntu 24.04 / Mint 22.x** (Python 3.12) or **Debian 12** (3.11) — nothing extra needed, `python3-dev` is the right package. Fandango requires **≥3.11** (`fandango/pyproject.toml`), and 3.12 is what the Docker image uses, so it is the tested version |
| **Older bases** | Ubuntu 22.04 / Mint 21 default to 3.10 and 20.04 to 3.8. 3.11 is **not in their archives** — it needs deadsnakes: `add-apt-repository ppa:deadsnakes/ppa && apt update && apt install python3.11 python3.11-dev`. Rebuilding on a 24.04 image is cleaner if that is cheap |
| **Matching headers** | Whatever the base, the CPython headers must match the `python3` that pip runs under. Plain `python3-dev` tracks the **distro default**, so on a box where you added a newer python it silently installs the *old* headers and Fandango's CMake step fails with `Could NOT find Python3 (missing: Development.Module)` / `Cannot find the directory "/usr/include/python3.11"`. The provision script derives the version from the live interpreter and probes for `Python.h` before building. A hand-built or pyenv python first on `PATH` is the usual cause — check `which -a python3` |
| **Repo access** | The repo is private. Register an SSH key with the CISPA GitLab, or use an HTTPS token (below) |
| **Disk** | ~65 GB and ~7M files per 3000-row window |
| **Inodes** | Check `df -i`. Default `mkfs.ext4` gives ~6.1M inodes per 100 GB — fewer than one window needs, so you hit `No space left on device` with space free. Format with `mkfs.ext4 -i 4096`, or use XFS |
| **Memory cap** | Set on the container: `limits.memory` (Incus/LXD) or `lxc.cgroup2.memory.max`. With host swap disabled an uncapped run OOM-kills the host |

## 1. Provision

```bash
apt-get update && apt-get install -y git
git clone git@projects.cispa.saarland:c01abal/verbal.git /opt/verbal
bash /opt/verbal/lxc_provision.sh /opt/verbal
```

With a token instead of SSH — GitLab → *Settings → Access Tokens*, `read_repository` scope:

```bash
git clone https://<user>:<token>@projects.cispa.saarland/c01abal/verbal.git /opt/verbal
```

The script installs system deps, the three pinned engines into `/usr/local/bin`, the Fandango
fork, writes `.engine-pins.json`, asserts the pins, and runs the smoke test. A few minutes,
mostly downloads.

If it fails partway, or the base image needs hand-holding the script does not do,
[`LXC_MANUAL_SETUP.md`](LXC_MANUAL_SETUP.md) is the same provisioning broken into pasteable
steps, each with its expected output and the failure it guards against.

`/opt/verbal` is arbitrary — pass any path, nothing outside the repo is assumed. The engines are
the one exception: they install to `/usr/local/bin`, which is deliberate, since they must be
first on `PATH` for the pins to hold.

## 2. Point `results/` at real storage

There is no bind mount here, so output lands in `<repo>/results` unless you redirect it:

```bash
mkdir -p /srv/verbal-results
ln -s /srv/verbal-results /opt/verbal/results
```

## 3. Verify

Fast check (3s, already run by the provision script):

```bash
cd /opt/verbal && PYTHON=python3 tests/smoke_test.sh
```

Expect `SMOKE PASS: all four pipeline stages produced output`. `PYTHON=python3` is required —
the default is a repo venv at `./bin/python` that does not exist here.

Full check (~30 min on 48 cores, 10 real regexes — proves both phases and the artifact layout):

```bash
cd /opt/verbal && mkdir -p results/smoke
START=0 TOTAL=10 WINDOWS=1 CHUNK=10 GEN_BUDGET=900 WORKERS=4 \
  CONFIG=config/fullcorpus.yaml PY=python3 OUTDIR=results/smoke \
  analysis/eval_help_scripts/scoped_run.sh

python3 -c "import json;d=json.load(open('results/eval_headline_0_10.json'));print(d['complete'], d['totals'])"
```

Expect `complete: true`, **0 discrepancies** (a pass — 10 regexes off the front of the corpus
are unremarkable) and `1 skipped_non_regex` (row 0 has `pattern: false`).

## 4. Run an experiment

Use `START=25000 TOTAL=3000`. Rows **0–20035** are already used; note a window's last chunk
over-reads past its nominal end, so check headline filenames rather than launch parameters.

```bash
cd /opt/verbal
NAME=run_25000
mkdir -p results/$NAME

systemd-run --unit=verbal-$NAME --working-directory=/opt/verbal \
  bash -lc "
    START=25000 TOTAL=3000 WINDOWS=8 CHUNK=100 GEN_BUDGET=36000 WORKERS=8 \
    REDOS_DEFER=1 CONFIG=config/fullcorpus.yaml PY=python3 OUTDIR=results/$NAME \
    analysis/eval_help_scripts/scoped_run.sh > results/$NAME/scoped_run.log 2>&1"
```

Size `WINDOWS` (Phase A parallelism) and `WORKERS` (Phase B) to your cores; keep
`REDOS_DEFER=1`. Full knob reference in
[the README](README.md#scoped_runsh-settings).

Runs take 15–30h, so launch detached — `systemd-run`, `tmux`, or `setsid`. Watch
`results/$NAME/scoped_run.log`, not `journalctl`; the driver redirects there and the journal
stays empty.

## Gotchas

- **`Unable to locate package` after provisioning?** Run `apt-get update` first. Earlier versions
  of `lxc_provision.sh` ended with `rm -rf /var/lib/apt/lists/*` (a Docker layer-shrinking idiom),
  which leaves apt with no index — every install then fails in a way that looks like the package
  is missing from the release. The script no longer does this, but a container provisioned by an
  older copy is still in that state.
- **Run the pin check before every experiment**: `python3 docker/assert_engine_versions.py`.
  Nothing runs it automatically outside Docker, and drifted engines make results incomparable.
- **Artifacts land in `results/`, not `OUTDIR`.** `OUTDIR` holds only driver logs and chunk
  records.
- **Headlines are per window**: `eval_headline_<start>_<end>.json`.
- **Don't change HEAD mid-run.** Phase B's `--resume` matches on git commit, so a commit during
  a run makes a later resume recompute the whole window.
- **`*.md` is gitignored**; docs are force-added. `grep` skips them — use
  `find . -name '*.md' -print0 | xargs -0 grep -n ...`.
- **`--cpuset` equivalent** is `limits.cpu` / `lxc.cgroup2.cpuset.cpus`. Keep it constant across
  windows if you care about ReDoS timing comparability.
