# Experiment image: the Python pipeline plus all three JS regex engines in ONE
# image. Python spawns node/bun/deno as subprocesses exactly as it does on bare
# metal, so there is no per-call container overhead; a full eval is ~1M
# short-lived engine spawns, which one-container-per-engine could not sustain.
#
# Engine versions are pinned to exactly what produced the reported results
# (node v26.5.0, bun 1.3.14, deno 2.9.1), downloaded from official release
# artifacts by exact version rather than a distro "latest" channel, and verified
# at container start (docker/entrypoint.sh -> docker/assert_engine_versions.py).

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
# Fandango is built from upstream at a pinned commit with patches/ applied: the
# pipeline needs a customizable tree search and surrogate-permitting encode/decode.
# Installed non-editable -- the build uses scikit-build-core, whose editable mode
# needs extra configuration and buys nothing in an image whose code is fixed at
# build time. Copied before the pipeline source so this layer caches independently
# of code edits.
ARG FANDANGO_COMMIT=01be7a03de16f3dfbd95fb1596884245b5f333e3
COPY requirements.txt /app/requirements.txt
COPY patches /app/patches
RUN set -eux; \
    git clone https://github.com/fandango-fuzzer/fandango.git /app/fandango; \
    cd /app/fandango; \
    git checkout "$FANDANGO_COMMIT"; \
    git apply /app/patches/fandango-verbal.patch; \
    pip install --no-cache-dir /app/fandango; \
    pip install --no-cache-dir -r /app/requirements.txt

# --- Pipeline code + inputs ---
COPY . /app
RUN chmod +x /app/docker/entrypoint.sh

# Bake the source commit for provenance: the repo's .git is excluded from the
# build context, so live `git` cannot run in the image. docker/build.sh computes
# and passes this. Empty when unset, so provenance records "unknown" rather than a
# fabricated hash.
ARG GIT_COMMIT=""
RUN printf '%s' "$GIT_COMMIT" > /app/.git-commit

# Verify engine pins on every container start, then run the given command.
# A version drift aborts the run instead of silently producing
# non-reproducible numbers.
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["/bin/bash"]
