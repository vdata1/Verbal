# Verbal experiment image: Python pipeline + the three JS regex engines, all in
# ONE image. Python spawns node/bun/deno as in-process subprocesses exactly as it
# does on bare metal (see eval/run_eval.py:run_engine) -- there is no per-call
# container overhead. A full eval is ~1M short-lived engine spawns; putting each
# engine in its own container would be catastrophic, so we deliberately do not.
#
# Engine versions are PINNED to exactly what produced the recorded results
# (results/eval_headline.json: node v26.5.0, bun 1.3.14, deno 2.9.1). They are
# downloaded from official release artifacts by exact version -- not from a
# distro "latest" channel -- and verified at container start (docker/entrypoint.sh
# -> docker/assert_engine_versions.py). This closes the reproducibility gap where
# the runner previously used whatever `node` happened to be first on PATH.

FROM python:3.12-slim

# Pinned engine versions. Change here (and rebuild) to re-pin deliberately; the
# provenance of these exact values is results/eval_headline.json.
ARG NODE_VERSION=26.5.0
ARG BUN_VERSION=1.3.14
ARG DENO_VERSION=2.9.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps: build tools for any native pip builds, plus the fetch/unpack tools
# the engine installs need (curl, xz for node's .tar.xz, unzip for bun/deno zips).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
        ca-certificates \
        curl \
        git \
        unzip \
        xz-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --- JS engines, pinned to exact versions, from official release artifacts ---
# All three land on PATH in /usr/local/bin. Arch is derived so the same Dockerfile
# builds on amd64 and arm64 servers.
RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    case "$ARCH" in \
        amd64) NODE_ARCH=x64;   BUN_ARCH=x64;     DENO_ARCH=x86_64-unknown-linux-gnu ;; \
        arm64) NODE_ARCH=arm64; BUN_ARCH=aarch64; DENO_ARCH=aarch64-unknown-linux-gnu ;; \
        *) echo "unsupported architecture: $ARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSLo /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"; \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 --no-same-owner; \
    curl -fsSLo /tmp/bun.zip "https://github.com/oven-sh/bun/releases/download/bun-v${BUN_VERSION}/bun-linux-${BUN_ARCH}.zip"; \
    unzip -q /tmp/bun.zip -d /tmp/bun; \
    mv "/tmp/bun/bun-linux-${BUN_ARCH}/bun" /usr/local/bin/bun; \
    chmod +x /usr/local/bin/bun; \
    curl -fsSLo /tmp/deno.zip "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-${DENO_ARCH}.zip"; \
    unzip -q /tmp/deno.zip -d /tmp/deno; \
    mv /tmp/deno/deno /usr/local/bin/deno; \
    chmod +x /usr/local/bin/deno; \
    rm -rf /tmp/node.tar.xz /tmp/bun /tmp/bun.zip /tmp/deno /tmp/deno.zip; \
    node --version; bun --version; deno --version

# Single source of truth the runtime assert checks live engines against.
RUN printf '{"node":"%s","bun":"%s","deno":"%s"}\n' \
        "$NODE_VERSION" "$BUN_VERSION" "$DENO_VERSION" > /app/.engine-pins.json

# --- Python deps ---
# Fandango is the forked build (github.com/reallyTG/fandango-slight-change), cloned
# into ./fandango. Installed NON-editable: the fork uses scikit-build-core (native
# build), whose editable mode needs extra config and buys nothing in an image where
# the code is fixed at build time -- to pick up fork changes you rebuild anyway.
# Copy it + requirements first so this dependency layer caches independently of
# pipeline-code edits.
COPY requirements.txt /app/requirements.txt
COPY fandango /app/fandango
RUN pip install --no-cache-dir /app/fandango \
    && pip install --no-cache-dir -r /app/requirements.txt

# --- Pipeline code + inputs (src/, eval/, config/, data/, docker/, tests/) ---
COPY . /app
RUN chmod +x /app/docker/entrypoint.sh

# Bake the source commit for provenance. The repo's .git is excluded from the build
# context (see .dockerignore), so live `git` can't run in the image; pass the real
# host commit at build time. docker/build.sh computes and passes this automatically.
# Empty when unset -> provenance honestly records "unknown" rather than a fake hash.
ARG GIT_COMMIT=""
RUN printf '%s' "$GIT_COMMIT" > /app/.git-commit

# Verify engine pins on every container start, then run the given command.
# Fail-loud: a version drift aborts the run instead of silently producing
# non-reproducible numbers (CLAUDE.md).
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["/bin/bash"]
