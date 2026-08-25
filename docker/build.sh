#!/bin/sh
# Build the Verbal image with the source commit baked in for provenance.
#
# The repo's .git is excluded from the image (see .dockerignore), so `git` can't run
# inside the container. This wrapper captures the REAL host commit (+ -dirty marker)
# at build time and passes it as the GIT_COMMIT build arg, so provenance records the
# exact code the image was built from instead of "unknown". Any extra args are
# forwarded to `docker compose build` (e.g. --no-cache).
#
# Usage:  ./docker/build.sh [extra docker-compose build args]
set -e

# Resolve repo root from this script's location so it works from any CWD.
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if git rev-parse --git-dir >/dev/null 2>&1; then
    COMMIT=$(git rev-parse HEAD)
    if [ -n "$(git status --porcelain)" ]; then
        COMMIT="${COMMIT}-dirty"
    fi
else
    echo "warning: not a git repo; provenance will record an empty/unknown commit" >&2
    COMMIT=""
fi

echo "baking GIT_COMMIT=${COMMIT:-<empty>}"
GIT_COMMIT="$COMMIT" docker compose build "$@"
