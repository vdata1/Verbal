#!/usr/bin/env bash
# Provision Verbal inside an LXC system container -- natively, no Docker.
#
# This is a direct port of the Dockerfile's install steps. An LXC container is a
# SYSTEM container (full userspace, apt, systemd), so the pinned-engine install is
# identical to the image's. Running Docker inside LXC would need security.nesting
# plus AppArmor work and buys nothing: the LXC container is already the isolation
# boundary.
#
# Native is also strictly better for provenance. `config._git_commit()` prefers live
# git, and the "dubious ownership + shadowed .git-commit" failure that recorded
# unknown-CalledProcessError across all 6.9M cases of the 6000-10050 window was
# CAUSED by bind-mounting the repo over /app as root. No bind mount, no such class
# of bug.
#
# Run as root inside the container.  Usage:  bash lxc_provision.sh [/opt/verbal]
#
# See RUN_ON_LXC.md for what to do after this finishes.
set -euo pipefail

REPO="${1:-/opt/verbal}"

# Keep in step with the Dockerfile ARGs; provenance of these values is the recorded
# per-window headlines (results/eval_headline_<start>_<end>.json).
NODE_VERSION=26.5.0
BUN_VERSION=1.3.14
DENO_VERSION=2.9.1

# --- system deps (Dockerfile lines 29-39, plus python which the image gets from
# --- its base layer) ---------------------------------------------------------
apt-get update
# The CPython headers are NOT optional and are NOT in the Dockerfile's list: the
# image's python:3.12-slim base already ships them. On a bare distro they are a
# separate package, and without them the Fandango build fails -- either
# "fatal error: Python.h: No such file or directory" from the Cython extension of its
# accumulation-tree dependency, or, from its own CMake step,
# 'Could NOT find Python3 (missing: Development.Module)'.
apt-get install -y --no-install-recommends \
    build-essential libffi-dev libssl-dev ca-certificates \
    curl git unzip xz-utils \
    python3 python3-pip python3-venv
# NOTE: deliberately no `rm -rf /var/lib/apt/lists/*` here or below. That is a Docker
# idiom for shrinking a layer; this container is long-lived, and wiping the index leaves
# the operator unable to `apt-get install` anything afterwards -- every attempt fails
# with "Unable to locate package", which reads as "this release does not have it" and
# sends you hunting a distro problem that does not exist. `apt-get clean` only drops the
# downloaded .debs and is harmless.
apt-get clean

# Headers for the interpreter we will ACTUALLY build against, which is not always the
# one `python3-dev` gives you. That package tracks the distro's DEFAULT python3; on a
# base whose default is older than Fandango's 3.11 floor (Ubuntu 22.04 and its Mint 21
# derivatives default to 3.10), you add 3.11 yourself, `python3` becomes 3.11, and
# `python3-dev` still installs the 3.10 headers. The build then finds a 3.11
# interpreter with no matching /usr/include/python3.11 and dies in CMake.
PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
    echo "ERROR: python3 is $PYV; Fandango requires >= 3.11." >&2
    echo "       Install a newer python3 and make it the python3 on PATH, then re-run." >&2
    exit 1
}
apt-get install -y --no-install-recommends "python${PYV}-dev" ||
    apt-get install -y --no-install-recommends python3-dev
apt-get clean

# Verify rather than trust the package name: this is exactly what CMake's
# find_package(Python3 ... Development.Module) looks for, so checking it here fails in
# one obvious line instead of 90 lines of build log. A source-built or pyenv python
# needs no apt package at all and passes straight through.
if ! python3 - <<'PY'
import os, sys, sysconfig
inc = sysconfig.get_paths()["include"]
if not os.path.exists(os.path.join(inc, "Python.h")):
    sys.stderr.write(f"missing {inc}/Python.h (python {sys.version.split()[0]} at {sys.executable})\n")
    raise SystemExit(1)
print(f"CPython headers OK: {inc}")
PY
then
    echo "ERROR: no Python.h for the python3 on PATH." >&2
    echo "       If that python is not the distro's own (check 'which -a python3'; a" >&2
    echo "       source-built or pyenv one first on PATH is the usual cause), its -dev" >&2
    echo "       package may not exist in this release at all -- Ubuntu 24.04 ships no" >&2
    echo "       python3.11. Prefer the distro python: install python3.12-dev and re-run" >&2
    echo "       with PY=python3.12." >&2
    exit 1
fi

# --- pinned engines into /usr/local/bin (Dockerfile lines 44-62) -------------
# /usr/local/bin matters: scoped_run.sh prepends an nvm path
# ($HOME/.nvm/versions/node/v26.5.0/bin) that will not exist here. A nonexistent
# PATH entry is a harmless no-op, but ONLY if the pinned node is already first on
# the base PATH. Do not install these via nvm or apt -- distro channels track
# "latest" and would silently break the pins.
ARCH="$(dpkg --print-architecture)"
case "$ARCH" in
    amd64) NODE_ARCH=x64;   BUN_ARCH=x64;     DENO_ARCH=x86_64-unknown-linux-gnu ;;
    arm64) NODE_ARCH=arm64; BUN_ARCH=aarch64; DENO_ARCH=aarch64-unknown-linux-gnu ;;
    *) echo "unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

curl -fsSLo /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 --no-same-owner

curl -fsSLo /tmp/bun.zip "https://github.com/oven-sh/bun/releases/download/bun-v${BUN_VERSION}/bun-linux-${BUN_ARCH}.zip"
unzip -q /tmp/bun.zip -d /tmp/bun
mv "/tmp/bun/bun-linux-${BUN_ARCH}/bun" /usr/local/bin/bun
chmod +x /usr/local/bin/bun

curl -fsSLo /tmp/deno.zip "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-${DENO_ARCH}.zip"
unzip -q /tmp/deno.zip -d /tmp/deno
mv /tmp/deno/deno /usr/local/bin/deno
chmod +x /usr/local/bin/deno

rm -rf /tmp/node.tar.xz /tmp/bun /tmp/bun.zip /tmp/deno /tmp/deno.zip
node --version; bun --version; deno --version

# --- repo + python deps ------------------------------------------------------
# Normally you have already cloned and are running this script out of the clone (see
# RUN_ON_LXC.md); this is only a fallback. The repo is PRIVATE -- anonymous HTTPS fails
# with "could not read Username" -- so this needs either an SSH key registered with the
# CISPA GitLab or a token-bearing HTTPS URL. Override with REPO_URL if you use a token.
REPO_URL="${REPO_URL:-git@projects.cispa.saarland:c01abal/verbal.git}"
if [ ! -d "$REPO/.git" ]; then
    git clone "$REPO_URL" "$REPO" || {
        echo "ERROR: clone of $REPO_URL failed -- the repo is private." >&2
        echo "       Register an SSH key with the CISPA GitLab, or re-run with" >&2
        echo "       REPO_URL='https://<user>:<token>@projects.cispa.saarland/c01abal/verbal.git'" >&2
        exit 1
    }
fi
cd "$REPO"

# The fork's directory name differs from the repo name, so the explicit target is
# required (README, "Setup (without Docker)").
if [ ! -d "$REPO/fandango" ]; then
    git clone https://github.com/reallyTG/fandango-slight-change.git "$REPO/fandango"
fi

# Non-editable, matching the image: the fork uses scikit-build-core (native build),
# whose editable mode needs extra config and buys nothing here.
# --break-system-packages is needed on Debian 12+ / Ubuntu 24.04+ (PEP 668); drop it
# on older bases, or create a venv at the repo root and unset PY below.
PIPFLAGS="--no-cache-dir --break-system-packages"
pip3 install $PIPFLAGS "$REPO/fandango"
pip3 install $PIPFLAGS -r "$REPO/requirements.txt"

# --- engine pins -------------------------------------------------------------
# .engine-pins.json is NOT tracked (it is in .git/info/exclude), so a fresh clone
# does not have it -- the Dockerfile generated it at build time from the same ARGs.
# It must be written by hand here or the pin check has nothing to read.
printf '{"node":"%s","bun":"%s","deno":"%s"}\n' \
    "$NODE_VERSION" "$BUN_VERSION" "$DENO_VERSION" > "$REPO/.engine-pins.json"

# assert_engine_versions.py resolves the pins file relative to its own location, so
# it works at any install prefix and needs no /app symlink. It is invoked ONLY by the
# Docker entrypoint, though -- outside Docker nothing runs it automatically, so run it
# by hand before every experiment or engine drift goes unnoticed (RUN_ON_LXC.md).
#
# Prints its own "engine pins OK: ..." line on success, so do not echo it again here.
python3 "$REPO/docker/assert_engine_versions.py"

# --- verify ------------------------------------------------------------------
# Fast plumbing check: all four pipeline stages on the tiny sample corpus, in an
# isolated temp dir that never touches results/. PYTHON=python3 is required -- the
# script defaults to the repo venv at ./bin/python, which does not exist here.
PYTHON=python3 "$REPO/tests/smoke_test.sh"

cat <<EOF

Provisioned at $REPO.

Next: cap the container's memory (see RUN_ON_LXC.md -- with swap disabled an
unbounded run OOM-kills the HOST, not the container), then start a run detached:

  cd $REPO
  systemd-run --unit=verbal-run --working-directory=$REPO \\
    --setenv=PY=python3 \\
    bash -lc 'mkdir -p results/run_25000 && \\
      START=25000 TOTAL=3000 WINDOWS=8 CHUNK=100 GEN_BUDGET=36000 WORKERS=8 \\
      REDOS_DEFER=1 CONFIG=config/fullcorpus.yaml PY=python3 OUTDIR=results/run_25000 \\
      analysis/eval_help_scripts/scoped_run.sh > results/run_25000/scoped_run.log 2>&1'
EOF
