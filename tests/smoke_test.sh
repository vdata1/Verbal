#!/usr/bin/env bash
# End-to-end smoke test for the Verbal pipeline.
#
# Runs all four stages (generate grammars -> fuzz -> unit tests -> diff test) on
# the tiny sample corpus (data/uniq-regexes-sample.json), in an ISOLATED temp
# root, so it never touches the real results/. Asserts each stage produced
# output. See CLAUDE.md: "Maintain a smoke test that runs the full pipeline
# end-to-end on tiny fixtures, so refactors can't silently change behavior."
#
# Usage:   tests/smoke_test.sh
# Env:     PYTHON=/path/to/python  (defaults to the repo venv at ./bin/python)
#
# Note: the diff-test stage shells out to node/deno/bun; if a runtime is missing
# it is recorded as an error per test but the pipeline still completes, so the
# structural smoke check still passes. Install all three for a meaningful diff.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$REPO_ROOT/bin/python}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Copy (do NOT symlink) src so PROJECT_ROOT in src/paths.py resolves to $WORK and
# every output lands under $WORK/results. Python resolves a symlinked script
# directory to its real target, which would defeat the isolation.
cp -R "$REPO_ROOT/src" "$WORK/src"
mkdir -p "$WORK/data"
cp "$REPO_ROOT/data/uniq-regexes-sample.json" "$WORK/data/"

cd "$WORK"
"$PY" src/main.py -g -n 1 -f -fn 10 -u -un 2 -d -dn 1 -k 2 \
      -r data/uniq-regexes-sample.json

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }
[ -s "$WORK/results/generation_record.json" ] \
    || fail "stage 1: no generation_record.json"
ls "$WORK"/results/generated_grammars/regex_* >/dev/null 2>&1 \
    || fail "stage 1: no grammars generated"
ls "$WORK"/results/generated_test_inputs/*_inputs.json >/dev/null 2>&1 \
    || fail "stage 2: no fuzzed inputs"
[ "$(find "$WORK/results/generated_unit_tests" -name '*.js' | wc -l)" -gt 0 ] \
    || fail "stage 3: no unit tests generated"
ls "$WORK"/results/diff_test_results/diff_test_results_*.json >/dev/null 2>&1 \
    || fail "stage 4: no diff-test results"

echo "SMOKE PASS: all four pipeline stages produced output"
