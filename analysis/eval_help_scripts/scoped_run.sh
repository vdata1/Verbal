#!/usr/bin/env bash
# Scoped end-to-end differential run at HEAD on the pinned engines, in ONE launch:
#
#   Phase A  chunked generation  (WINDOWS parallel overnight_drive.sh instances over
#            disjoint sub-windows -> ONE fresh OUTDIR of chunks + HEAD harnesses under
#            results/regex_*/)                          -- time-boxed, resumable
#   Adapter  chunks -> results/run_record_<start>_<end>.json  (chunks_to_run_record.py)
#   Phase B  parallel differential eval               (run_eval --skip-generate
#            --resume --record R --workers N -> per-(regex,api) diff.json +
#            results/eval_headline_<start>_<end>.json)
#
# WINDOWS (default 1) closes EXPERIMENT_GAPS G4: it fans out N generation drivers over
# disjoint START offsets into the shared OUTDIR, BARRIERS on all of them, then runs the
# adapter ONCE and a SINGLE eval over the merged window. This is what makes a large
# window fit overnight without the old failure mode -- generating in parallel by hand
# and then hand-launching the eval ~14h later. Generation is parallel; the adapter and
# eval stay single (running N of them would race on the derived record filename).
# Chunk files are keyed by GLOBAL start index, so N drivers never collide; each keeps
# its own drive_<start>.log. GEN_BUDGET is PER-driver wall-clock, and drivers run
# concurrently, so the generation phase finishes in ~GEN_BUDGET regardless of N.
#
# Sized to fit an ~8h window (default 1500 rows: ~gen 4.5h + eval ~2h, with a 5h
# generation cap so a slow gen still leaves time to eval whatever completed).
# Resumable at EVERY stage: rerun the SAME command and completed chunks are skipped
# (Phase A) and provenance+engine-matching diffs are reused (Phase B).
#
# Every knob is a uniform global (env override), no per-instance logic.
#
# Usage:   analysis/eval_help_scripts/scoped_run.sh
# Tune:    START=0 TOTAL=1500 WINDOWS=1 CHUNK=100 GEN_BUDGET=18000 WORKERS=12 \
#              OUTDIR=results/overnight_head  analysis/eval_help_scripts/scoped_run.sh
# Regen the 6000-9999 window 8-way:
#          START=6000 TOTAL=4000 WINDOWS=8 CONFIG=config/fullcorpus.yaml PY=python3 \
#              OUTDIR=results/regen_6000 analysis/eval_help_scripts/scoped_run.sh
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || { echo "cannot cd to repo root $ROOT"; exit 1; }

# Pin node v26 (nvm's `default` alias is NOT applied in a non-interactive shell, so
# a bare `node` would resolve to v20). bun/deno come from Homebrew on the base PATH.
# node is needed in BOTH phases: the generation JS-validity gate and the eval engines.
export PATH="$HOME/.nvm/versions/node/v26.5.0/bin:$PATH"

CONFIG="${CONFIG:-config/overnight.yaml}"
START="${START:-0}"                    # base corpus offset (first row of the window)
TOTAL="${TOTAL:-1500}"                 # corpus rows to cover from START
WINDOWS="${WINDOWS:-1}"                # parallel gen drivers over disjoint sub-windows (G4)
CHUNK="${CHUNK:-100}"                  # rows per fresh gen subprocess (bounds RSS)
GEN_BUDGET="${GEN_BUDGET:-18000}"      # PER-driver wall-clock cap (drivers run concurrently)
WORKERS="${WORKERS:-12}"               # eval parallelism (<= cores; not in provenance)
REDOS_DEFER="${REDOS_DEFER:-0}"        # 1 = queue ReDoS candidates, confirm off-box later
export OUTDIR="${OUTDIR:-results/overnight_head}"   # FRESH dir -- never the stale chunks

[ "$WINDOWS" -ge 1 ] || { echo "WINDOWS must be >= 1, got $WINDOWS"; exit 1; }

# Interpreter (env override); see overnight_drive.sh. PY=python3 in the Docker image.
PY="${PY:-./bin/python}"

echo "=== scoped_run start $(date) ==="
echo "engines: node=$(node -v) bun=$(bun -v) deno=$(deno -V | head -1)"
echo "config=$CONFIG start=$START total=$TOTAL windows=$WINDOWS chunk=$CHUNK gen_budget=${GEN_BUDGET}s workers=$WORKERS redos_defer=$REDOS_DEFER outdir=$OUTDIR"

# --- Provenance preflight -----------------------------------------------------
# A window that cannot be traced to code is a window that has to be re-run. The
# 6000-10050 run recorded git_commit "unknown-CalledProcessError" for all 6.9M of its
# cases, and the cause was invisible from either side on its own: bind-mounting the
# repo over /app made `git rev-parse` fail with "dubious ownership" (host-owned tree,
# root container) AND shadowed the image's baked /app/.git-commit, so both links of the
# fallback chain broke together. `config._git_commit` now passes `-c safe.directory=*`
# and reads the mounted tree, which is the commit actually being executed.
# This check is the backstop, and it is deliberately environment-agnostic: it asks the
# pipeline what it WOULD record, here, now -- so it catches the next cause too, not
# just this one. Two seconds, against a window's worth of untraceable cases.
COMMIT_RECORDED="$("$PY" -c 'import sys; sys.path.insert(0, "src"); from pipeline.config import recorded_commit; print(recorded_commit())')" || {
    echo "provenance preflight could not run ($PY / src import failed) -- aborting"; exit 1; }
case "$COMMIT_RECORDED" in
  ""|unknown-*)
    echo "ABORT: provenance would record git_commit='${COMMIT_RECORDED:-<empty>}'."
    echo "  This window's artifacts would not be traceable to any commit."
    echo "  If running in a container over a bind-mounted repo, check .git is inside the"
    echo "  mount; if running from an image copy, rebuild with ./docker/build.sh."
    echo "  Override for a throwaway run with: ALLOW_UNKNOWN_COMMIT=1"
    [ "${ALLOW_UNKNOWN_COMMIT:-0}" = "1" ] || exit 1
    echo "  ALLOW_UNKNOWN_COMMIT=1 set -- proceeding UNTRACEABLE."
    ;;
  *-dirty)
    # Not fatal: a dirty tree is recorded honestly and is normal for a scoped run.
    echo "provenance: git_commit=$COMMIT_RECORDED (uncommitted changes -- recorded as dirty)"
    ;;
  *)
    echo "provenance: git_commit=$COMMIT_RECORDED"
    ;;
esac

echo "=== Phase A: ${WINDOWS}-way parallel chunked generation @ HEAD (per-driver ${GEN_BUDGET}s) ==="
END=$((START + TOTAL))
# ceil(TOTAL/WINDOWS) so the sub-windows tile [START, END) with no gap; the last is
# clamped to END so we never generate past TOTAL. WINDOWS=1 -> one driver over the
# whole window (the historical serial behaviour, so this is backward compatible).
PER=$(( (TOTAL + WINDOWS - 1) / WINDOWS ))
pids=(); pid_starts=()
s=$START; w=0
while [ "$s" -lt "$END" ] && [ "$w" -lt "$WINDOWS" ]; do
  count=$(( END - s < PER ? END - s : PER ))
  echo "  [window $w] rows [$s, $((s + count))) -> $OUTDIR/drive_${s}.log"
  START="$s" analysis/eval_help_scripts/overnight_drive.sh "$CONFIG" "$count" "$CHUNK" "$GEN_BUDGET" &
  pids+=("$!"); pid_starts+=("$s")
  s=$((s + PER)); w=$((w + 1))
done

# Barrier: wait for EVERY driver before the adapter runs. A driver that fails leaves
# its completed chunks behind; the adapter merges whatever exists, so we warn and
# proceed (partial coverage is still evaluable) rather than abort the whole run.
gen_fail=0
for i in "${!pids[@]}"; do
  if ! wait "${pids[$i]}"; then
    echo "[warn] generation driver START=${pid_starts[$i]} exited non-zero"
    gen_fail=$((gen_fail + 1))
  fi
done
echo "=== Phase A done: $w drivers launched, $gen_fail failed ==="

echo "=== Adapter: chunks -> per-window run record ==="
# The adapter names the record for the window the chunks actually cover (a time-boxed
# Phase A may stop short of TOTAL), and prints that path on stdout -- capture it and
# hand it to Phase B rather than guessing the filename.
RECORD="$("$PY" analysis/eval_help_scripts/chunks_to_run_record.py --outdir "$OUTDIR")"
[ -n "$RECORD" ] || { echo "adapter produced no run record -- aborting"; exit 1; }
echo "run record: $RECORD"

echo "=== Phase B: parallel differential eval (resume, workers=$WORKERS) ==="
# REDOS_DEFER=1 drops the serial ReDoS confirm from this box's critical path: the pool
# still NOMINATES candidates, but they are queued to results/redos_queue_<window>.json
# for an unloaded confirm elsewhere instead of being measured here. That phase is
# single-threaded (one core busy, the rest idle) and dominated the last two windows --
# 6h57m of a 17h18m run, 5h19m of the one before -- so deferring it is what lets a
# window cover more corpus rows in the same wall-clock.
# if/else rather than `[ test ] && VAR=...`: that idiom evaluates to non-zero on the
# DEFAULT (REDOS_DEFER=0) path, so it would abort the run the day someone adds `set -e`.
REDOS_ARGS=""
if [ "$REDOS_DEFER" = "1" ]; then
  REDOS_ARGS="--redos-defer"
fi
"$PY" eval/run_eval.py --skip-generate --resume --record "$RECORD" \
    --workers "$WORKERS" --config "$CONFIG" $REDOS_ARGS

echo "=== scoped_run end $(date) ==="
