#!/usr/bin/env bash
# Overnight generation-correctness driver: chunked, resumable, time-bounded.
#
# Runs the corpus in fixed-size chunks, each as a FRESH subprocess (bounds RSS and
# keeps per-regex time flat). Skips chunks whose result file already exists, so
# rerunning after a crash/kill RESUMES where it left off. Stops launching new chunks
# once TIME_BUDGET seconds have elapsed, then aggregates whatever completed.
#
# Every parameter is a general knob applied uniformly to all chunks (no per-instance
# logic). Defaults target an ~8h window over the 3000-row sample.
#
# Usage:
#   analysis/eval_help_scripts/overnight_drive.sh [CONFIG] [TOTAL] [CHUNK] [TIME_BUDGET_S]
# Resume: just run the SAME command again -- completed chunks are skipped.
#
# START (env, default 0) is the global corpus offset: the driver covers rows
# [START, START+TOTAL) in chunks, so a new window of NEW rows never re-touches
# earlier ones. START=0 is the historical behaviour (rows [0, TOTAL)), so this is
# backward compatible. Chunk files are keyed by GLOBAL start index
# (chunk_<start:06d>.json), which is what makes resume and disjoint windows work.
#
# NOTE: run from the repo root. Needs Bash-for-python permission pre-approved for
# an unattended run (see the handoff doc).

set -u

CONFIG="${1:-config/overnight.yaml}"
TOTAL="${2:-3000}"          # deterministic count of corpus rows to cover from START
CHUNK="${3:-100}"           # rows per fresh subprocess (bounds memory)
TIME_BUDGET="${4:-28800}"   # wall-clock seconds before stopping new chunks (8h)
START="${START:-0}"         # global corpus offset; covers rows [START, START+TOTAL)

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || { echo "cannot cd to repo root $ROOT"; exit 1; }

# Interpreter (env override). Defaults to the repo venv for a bare-metal run; set
# PY=python3 inside the Docker image, where the toolchain is already on PATH and
# there is no ./bin/python.
PY="${PY:-./bin/python}"
OUTDIR="${OUTDIR:-results/overnight}"   # override with OUTDIR=... for tests
mkdir -p "$OUTDIR"
# Per-window log: several drivers may cover disjoint windows into ONE outdir
# concurrently (chunk files are keyed by global start, so they never collide);
# a shared log would interleave their lines into an unreadable mess.
DRIVE_LOG="$OUTDIR/drive_${START}.log"

start_epoch=$(date +%s)
echo "=== overnight driver start $(date) ===" | tee -a "$DRIVE_LOG"
echo "config=$CONFIG start=$START total=$TOTAL chunk=$CHUNK budget=${TIME_BUDGET}s outdir=$OUTDIR" | tee -a "$DRIVE_LOG"
echo "covering corpus rows [$START, $((START + TOTAL)))" | tee -a "$DRIVE_LOG"

s=$START
END=$((START + TOTAL))
while [ "$s" -lt "$END" ]; do
  f=$(printf "%s/chunk_%06d.json" "$OUTDIR" "$s")
  if [ -f "$f" ]; then
    echo "[skip] chunk $s already done" | tee -a "$DRIVE_LOG"
    s=$((s + CHUNK)); continue
  fi
  now=$(date +%s); elapsed=$((now - start_epoch))
  if [ "$elapsed" -ge "$TIME_BUDGET" ]; then
    echo "[stop] time budget ${TIME_BUDGET}s reached (elapsed ${elapsed}s) at chunk $s" | tee -a "$DRIVE_LOG"
    break
  fi
  echo "[$(date +%H:%M:%S)] chunk start=$s count=$CHUNK (elapsed ${elapsed}s)" | tee -a "$DRIVE_LOG"
  "$PY" -u analysis/eval_help_scripts/overnight_run.py \
      --config "$CONFIG" --start "$s" --count "$CHUNK" --outdir "$OUTDIR" >>"$DRIVE_LOG" 2>&1
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "[warn] chunk $s exited rc=$rc -- left no file, will retry on rerun" | tee -a "$DRIVE_LOG"
  fi
  s=$((s + CHUNK))
done

echo "[$(date +%H:%M:%S)] driver loop finished; aggregating" | tee -a "$DRIVE_LOG"
"$PY" analysis/eval_help_scripts/overnight_aggregate.py --outdir "$OUTDIR" | tee -a "$DRIVE_LOG"
echo "=== overnight driver end $(date) ===" | tee -a "$DRIVE_LOG"
