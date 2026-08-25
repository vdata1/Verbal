# Manual monitor — `regen_6000` (rows 6000–9999 regeneration)

Quick-reference for checking on the detached run when you come back. Fuller narrative
lives in `analysis/HANDOFF_2026-07-21.md`.

## What's running

- **Container:** `regen_6000`, detached (`docker run -d` — survives SSH drops / this
  session closing).
- **Launched:** 16:07 UTC 2026-07-21.
- **Command that started it:**
  ```
  START=6000 TOTAL=4000 WINDOWS=16 WORKERS=40 GEN_BUDGET=28800 CHUNK=100 \
    CONFIG=config/fullcorpus.yaml PY=python3 OUTDIR=results/regen_6000 \
    analysis/eval_help_scripts/scoped_run.sh
  ```
- **Flow:** 16 parallel gen drivers over disjoint 250-row sub-windows → barrier →
  adapter once → single eval @ 40 workers → one headline. Gen and eval do NOT overlap.

## Snapshot at last check (2026-07-22, ~16h in)

- Gen finished **short: 3222/4000 rows** (time-boxed — the ~2.6 min/row rate would have
  blown the 8h GEN_BUDGET, so drivers cut their sub-windows short as designed).
- Eval in progress: ~15,800 / 25,072 units, ~4.38M cases, 2,279 discrepancies,
  0 defects, 132 timeouts (ReDoS candidates). ETA was ~2.5–3h from that check.
- Headline **not written yet**. Expect final `complete: false` (honest partial window,
  not broken).

## Check on it

```bash
cd ~/projects/verbal

# Running?
docker ps --filter name=regen_6000 --format '{{.Status}}'

# Live eval counter + phase lines
tail -f results/regen_6000/scoped_run.log

# Gen rows done /4000 (meaningful only during Phase A)
grep -hc '^\[regex_' results/regen_6000/drive_*.log | paste -sd+ | bc

# Done yet?
grep -o '"complete":[^,]*' results/eval_headline_6000_10000.json 2>/dev/null \
  || echo "headline not written yet"
```

- Gen→eval transition line: `=== Phase A done: 16 drivers launched, N failed ===`.
- **Done** when `scoped_run.log` ends with `=== scoped_run end …` AND
  `results/eval_headline_6000_10000.json` shows `complete: true` (here it'll be
  `false` — the intended partial).

## Where results land

- `results/eval_headline_6000_10000.json` — the headline.
- `results/regex_*/` — per-regex results.
- `results/run_record_6000_10000.json` — run record.

## When it's done — cleanup

Container has no `--rm` (kept so you can read post-hoc exit status). Once you've got the
headline:
```bash
docker rm regen_6000
```
The stale 6000–6500 partial previously in `results/` is overwritten by this window (intended).

## If you'd rather rerun wider (fuller/faster coverage)

Resumable — chunks are keyed by global start, completed ones skip. Box has 48 cores and
it's ~1 core/driver, so more windows = faster wall-clock:
```bash
docker kill regen_6000 && docker rm regen_6000
# relaunch same command with WINDOWS=32, reuse OUTDIR=results/regen_6000
START=6000 TOTAL=4000 WINDOWS=32 WORKERS=40 GEN_BUDGET=28800 CHUNK=100 \
  CONFIG=config/fullcorpus.yaml PY=python3 OUTDIR=results/regen_6000 \
  analysis/eval_help_scripts/scoped_run.sh
```

## Gotcha

If you kill the run from *inside a tool that reaps child processes*, the container can be
orphaned — reap it explicitly with `docker kill regen_6000` before `docker rm`.
