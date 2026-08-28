#!/usr/bin/env bash
# End-to-end smoke test: regex -> base.fan -> per-API .fan -> strings + harnesses
# -> node/bun/deno diff. Runs in an isolated temp root, so it never touches the
# real results/. Uses config/minimal.yaml.
#
# Usage:   tests/smoke.sh
# Env:     PYTHON=/path/to/python   (default: python3)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Copy rather than symlink, so PROJECT_ROOT in src/paths.py resolves to $WORK and
# every artifact lands under $WORK/results. Python resolves a symlinked script
# directory to its real target, which would defeat the isolation.
cp -R "$REPO_ROOT/src" "$WORK/src"
cp -R "$REPO_ROOT/eval" "$WORK/eval"
cp -R "$REPO_ROOT/config" "$WORK/config"
cp "$REPO_ROOT/verbal.py" "$WORK/verbal.py"
mkdir -p "$WORK/data"
cp "$REPO_ROOT/data/paper_eval_set_patterns.json" "$WORK/data/"

cd "$WORK"

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

# --- 1. Single-regex mode ----------------------------------------------------
"$PY" verbal.py --regex 'a+b' >/dev/null || fail "single-regex run exited non-zero"
[ -s "$WORK/results/regex_0/base.fan" ]            || fail "single: no base.fan"
[ -s "$WORK/results/regex_0/exec.diff.json" ]      || fail "single: no diff artifact"

rm -rf "$WORK/results"

# --- 2. Corpus-window mode ---------------------------------------------------
"$PY" verbal.py --limit 3 >/dev/null || fail "corpus run exited non-zero"

RID_DIR="$WORK/results/regex_0"
[ -s "$RID_DIR/base.fan" ]            || fail "stage 1: no base.fan"
[ -s "$RID_DIR/exec.fan" ]            || fail "stage 2: no exec.fan"
[ -s "$RID_DIR/matchAll.fan" ]        || fail "stage 2: no matchAll.fan"
[ -s "$RID_DIR/exec.strings.jsonl" ]  || fail "stage 3: no strings.jsonl"
ls "$RID_DIR"/exec__*.js >/dev/null 2>&1 || fail "stage 3: no harness .js"
[ -s "$RID_DIR/exec.diff.json" ]      || fail "eval: no diff artifact"

# Records and headlines are named for the window they cover, so a later window
# cannot overwrite this one.
RECORD="$WORK/results/run_record_0_3.json"
HEADLINE="$WORK/results/eval_headline_0_3.json"
[ -s "$HEADLINE" ] || fail "eval: no headline at $HEADLINE"
[ -s "$RECORD" ]   || fail "run: no run record at $RECORD"
[ ! -e "$WORK/results/run_record.json" ]    || fail "run: wrote a window-less run_record.json"
[ ! -e "$WORK/results/eval_headline.json" ] || fail "eval: wrote a window-less eval_headline.json"

"$PY" - "$RECORD" <<'PYEOF'
import json, sys
counts = json.load(open(sys.argv[1]))["counts"]
assert counts.get("ok", 0) >= 1, f"expected >=1 ok regex: {counts}"
print(f"run record counts OK: {counts}")
PYEOF

# The headline must state its window, so `complete` can never be read as a claim
# about rows it never evaluated.
"$PY" - "$HEADLINE" <<'PYEOF'
import json, sys
h = json.load(open(sys.argv[1]))
assert h["window"] == {"start": 0, "end": 3}, f"bad window: {h.get('window')}"
print(f"headline window OK: {h['window']} complete={h['complete']}")
PYEOF

# --skip-generate must resolve the same window's record and re-evaluate from it.
"$PY" eval/run_eval.py --config "$WORK/config/minimal.yaml" --limit 3 \
    --skip-generate --resume >/dev/null \
    || fail "eval: --skip-generate could not find the window record"

echo "SMOKE PASS: single-regex and corpus modes both produced full artifact chains"
