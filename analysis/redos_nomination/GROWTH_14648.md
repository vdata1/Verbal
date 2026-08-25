# Growth curves for `regex_14648` — the bun/V8 gap is a constant factor

**Verdict: not reportable.** All four engines are exponential in the same variable with the
same base, ≈ 2.0. bun is 12–16× cheaper at every length, and that factor does **not** grow
with n. Per the standard this project already set (`HANDOFF_redos_timing.md` R5, the
2026-08-03 triage §4b), a constant factor between two engines is not a finding about an
engine. This closes triage §6.

Date: 2026-08-12. Artifact: `growth_14648.json`. Driver: `growth_family.py`.
Measured on `shuttle01se`, 48 cores, loadavg 4.4 at start, on the pinned engines running
natively out of `/scratch/turcotte/pinned_engines` — no docker (HANDOFF_2026-08-11).

```
^(?:[^`"[]+|`[^`]*`|"[^"]*")* AS\s+
```

## Why this regex

Triage §6 picked it as the best growth-curve input in the 2026-08-07 confirm: 13 rows
fully measured on both sides, returning a real match, with bun 13–27× faster on
`replace`/`split`. Two-sided rows are rare — only 73 exist across all six windows — and a
matching row is rarer still. It was the strongest available candidate for a class
difference, which is what makes a negative result here worth recording.

## The measured answer

`tail` family, all four APIs, pinned engines running natively:

| api | engine | fitted base | R² | poly k | R² |
|---|---|---:|---:|---:|---:|
| replace | node v26.5.0 | 1.991 | 0.9992 | 39.0 | 0.9964 |
| replace | deno 2.9.1 | 2.032 | 0.9995 | 40.2 | 0.9993 |
| replace | bun 1.3.14 | 2.002 | 0.9993 | 41.8 | 0.9973 |
| replace | bun 1.4.0 | 1.988 | 0.9999 | 40.7 | 0.9980 |

All 32 exponential cells (`tail` and `fail` × 4 APIs × 4 engines) land between **1.974
and 2.032** — a spread of about 3%, on fits with R² ≥ 0.998. The competing power law
needs degree ~40 over this band, which is the exponential in disguise (`classify`'s
`k > 6` escape hatch).

Verdicts across the artifact: `tail` 16/16 EXPONENTIAL, `fail` 16/16 EXPONENTIAL, `match`
16/16 SAFE, `prefix` 15 UNCLASSIFIED + 1 LINEAR (all at ~0 ms — the flat control).

The constant factor, read at the longest length where all four engines have points:

| api | len | node | deno | bun | bun 1.4.0 | node/bun |
|---|---:|---:|---:|---:|---:|---:|
| test | 65 | 40.8 ms | 40.0 ms | 3.15 ms | 5.04 ms | 13.0× |
| replace | 64 | 20.0 ms | 20.4 ms | 1.33 ms | 2.73 ms | 15.0× |
| split | 65 | 39.7 ms | 38.0 ms | 3.18 ms | 5.50 ms | 12.5× |
| match | 65 | 39.8 ms | 39.9 ms | 3.16 ms | 4.93 ms | 12.6× |

Flat in n, which is the whole point: a class difference would show the ratio growing with
length. It does not. bun buys about 3 extra characters of tail at equal cost — 2³ ≈ 8,
consistent with the measured factor given where each engine crosses the stop threshold.

node and deno agree within 1.1× everywhere, as expected — same V8 (triage §3).

## Which length axis — measured, not assumed

The first family built for this study was wrong, and the way it was wrong is the useful
part. `"a"*n` with a matching tail reads **SAFE on every engine**: an ambiguous run
followed by a tail that matches is cheap. So the obvious family cannot speak for §6's
rows, which were slow *and* matching.

Growing the corpus prefix instead is **flat**: 76–79 ms on node from 66 to 281 chars, and
instant when the tail cannot match. Prefix length is not the axis either.

The cost is in the **trailing whitespace**. Every whitespace character is inside
`` [^`"[] ``, so branch 1 under the star can partition a run of n of them 2^(n-1) ways,
while the tail ` AS\s+` competes for the same characters. On node:

```
n=13  1.2 ms      n=19   67.9 ms      n=23  1238 ms
n=16  9.4 ms      n=21  312.8 ms      n=24  2487 ms
```

Doubling per added character, matching throughout. The real corpus string carries a
19-char whitespace tail and costs 68–79 ms natively — exactly where the family sits at
n=19. So `tail` is that string's own shape, parameterized, and `prefix` is kept in the
artifact as the negative control that establishes it.

## Native reproduction of the confirm row

`replace` #26, the verbatim corpus string, on the pinned engines:

| engine | median of 5 | artifact |
|---|---:|---:|
| node | 78.9 ms | 1214.1 ms |
| bun | 5.2 ms | 83.4 ms |
| **ratio** | **15.2×** | **14.7×** |

The ratio reproduces; the milliseconds are ~15× lower than the containerised confirm.
That is `confirm_redos.py`'s own stated contract — ratios travel, milliseconds do not —
observed directly. Worth noting the same run showed a 371 ms max against a 78.9 ms
median on node, the scheduling-stall artifact again: single readings on this box are
still worthless.

## Controls

The harness grew an `api` switch for this study, so a sweep that quietly measured the
wrong thing afterwards would look exactly like a clean result. `--controls` reruns the
nominator's known-answer regexes through the same path, including the new APIs:

| regex | expected | node | bun |
|---|---|---|---|
| `/(a+)+$/` | base 2.0 | 2.002 / 2.041 | 2.004 / 2.005 |
| `/(a\|aa)+$/` | base φ ≈ 1.618 | 1.625 / 1.624 | 1.630 / 1.629 |
| `/a+b/` | polynomial k ≈ 2 | k 1.92 / 1.95 | k 1.84 / 2.14 |

(`test` / `replace`.) Recovering φ to three decimals through the new `replace` path is
the check that matters.

## What this does and does not settle

Settled: on this regex, bun's advantage is a constant factor, and no engine here is in a
different complexity class. The 13 rows of §6 are not a bug in anything.

Not settled: this is **one** regex. It says nothing about the other 8 in the confirm, and
nothing about the 852 rows whose slow side was censored at the budget — those still lack
a two-sided reading at any length (triage §2a). What it does show is that the method
answers the question cheaply: the whole study is minutes of engine time on a quiet box,
against ~30 h for a window re-run at a longer budget, and it answers the class question
that a longer budget still could not.

The obvious follow-up is the same treatment on the remaining 8 regexes — and, since the
axis here turned out not to be the one that would have been assumed, with the axis found
per regex rather than presumed.
