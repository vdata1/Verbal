#!/bin/sh
# Verify pinned engine versions before doing anything, then exec the command.
# The assert is ~3 cheap `--version` calls; a mismatch aborts (fail loud) rather
# than letting a non-reproducible run proceed.
set -e
python3 /app/docker/assert_engine_versions.py
exec "$@"
