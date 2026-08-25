#!/usr/bin/env bash
# End-to-end smoke test for the NEW pipeline (regex -> base.fan -> per-API .fan ->
# strings + harnesses -> node/bun/deno diff). Runs in an ISOLATED temp root so it
# never touches the real results/. Uses config/smoke.yaml (tiny fuzz budget).
#
# This complements -- does not replace -- tests/smoke_test.sh (the old pipeline).
# See CLAUDE.md: "Maintain a smoke test that runs the full pipeline end-to-end on
# tiny fixtures, so refactors can't silently change behavior."
#
# Usage:   tests/new_pipeline_smoke.sh
# Env:     PYTHON=/path/to/python  (defaults to `python3`)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Copy (do NOT symlink) src/eval/config so PROJECT_ROOT in src/paths.py resolves to
# $WORK and every artifact lands under $WORK/results (isolation).
cp -R "$REPO_ROOT/src" "$WORK/src"
cp -R "$REPO_ROOT/eval" "$WORK/eval"
cp -R "$REPO_ROOT/config" "$WORK/config"
mkdir -p "$WORK/data"
cp "$REPO_ROOT/data/uniq-regexes-sample.json" "$WORK/data/"

cd "$WORK"
"$PY" eval/run_eval.py --config "$WORK/config/smoke.yaml" --limit 3

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

# At least one regex should have produced a full artifact chain. regex_0 in the
# sample corpus is `pattern: false` (skipped), so check regex_1.
RID_DIR="$WORK/results/regex_1"
[ -s "$RID_DIR/base.fan" ]              || fail "stage 1: no base.fan"
[ -s "$RID_DIR/exec.fan" ]             || fail "stage 2: no exec.fan"
[ -s "$RID_DIR/matchAll.fan" ]         || fail "stage 2: no matchAll.fan"
[ -s "$RID_DIR/exec.strings.jsonl" ]   || fail "stage 3: no strings.jsonl"
ls "$RID_DIR"/exec__*.js >/dev/null 2>&1 || fail "stage 3: no harness .js"
[ -s "$RID_DIR/exec.diff.json" ]       || fail "eval: no diff artifact"

# Run record + headline are named for the window they cover ([0,3) here, from
# --limit 3), so a later window cannot overwrite this one's results.
RECORD="$WORK/results/run_record_0_3.json"
HEADLINE="$WORK/results/eval_headline_0_3.json"
[ -s "$HEADLINE" ] || fail "eval: no headline at $HEADLINE"
[ -s "$RECORD" ]   || fail "run: no run record at $RECORD"
[ ! -e "$WORK/results/run_record.json" ]   || fail "run: wrote a window-less run_record.json"
[ ! -e "$WORK/results/eval_headline.json" ] || fail "eval: wrote a window-less eval_headline.json"

# The run record must show the non-string row classified, not crashed.
"$PY" - "$RECORD" <<'PYEOF'
import json, sys
rec = json.load(open(sys.argv[1]))
counts = rec["counts"]
assert counts.get("skipped_non_regex", 0) >= 1, f"expected a skipped non-regex row: {counts}"
assert counts.get("ok", 0) >= 1, f"expected >=1 ok regex: {counts}"
print(f"run record counts OK: {counts}")
PYEOF

# The headline must say which window it covers, so `complete` can never be read as
# a claim about rows it never evaluated.
"$PY" - "$HEADLINE" <<'PYEOF'
import json, sys
h = json.load(open(sys.argv[1]))
assert h["window"] == {"start": 0, "end": 3}, f"bad window: {h.get('window')}"
print(f"headline window OK: {h['window']} complete={h['complete']}")
PYEOF

# --skip-generate must resolve the SAME window's record and re-evaluate from it.
"$PY" eval/run_eval.py --config "$WORK/config/smoke.yaml" --limit 3 \
    --skip-generate --resume >/dev/null || fail "eval: --skip-generate could not find the window record"

echo "SMOKE PASS: new pipeline produced base/specialized/strings/harness/diff artifacts"
