"""How a confirmed ReDoS row's slowest/fastest gap is classified. ONE definition.

Three things need this and must agree exactly:

- ``run_eval._confirm_redos``   -- the inline confirm phase;
- ``confirm_redos._verdict``    -- the deferred confirm, run on a quiet box;
- the backfill that re-reads artifacts confirmed before the split existed.

Divergence between the first two makes a deferred window incomparable with an inline
one, which is the whole reason this is a module and not a copied expression. It is kept
dependency-free (like ``paths``) so the offline readers can import it without pulling in
the generation pipeline.
"""

from __future__ import annotations


def ratio_fields(ms: dict, timed_out: list, engine_ratio: float) -> dict:
    """Rank slowest vs fastest and classify the gap between them.

    ``ratio`` is only a MEASUREMENT when both ends were measured. A timed-out engine is
    scored at the harness budget (``run_eval._effective_ms``), so when the slowest engine
    is one that timed out, ``ratio = budget / fastest`` -- the slow side is a constant,
    and ``ratio >= engine_ratio`` reduces to ``fastest <= budget / engine_ratio``, a
    threshold on the FAST engine's time. Those rows are marked ``ratio_censored``.

    Censoring only ever understates the slow side, so this does NOT make a flagged row
    wrong -- the true ratio is at least the recorded one. It makes it UNRESOLVED at this
    budget, in both directions:

    - flagged + censored -> a sound lower bound, not a measured gap;
    - NOT flagged + censored -> not evidence of "no differential" either. The slow side
      was cut off at the same budget; only the fast engine's own time put the ratio under
      the gate. Observed live: one regex flagged true at no-flags and `d` and false at
      `g`, with node and deno censored at the harness budget in all three -- the verdict
      flipped on bun's own time, nothing about V8 was measured.

    So the components are reported apart, and censoring is recorded whether or not the
    row was flagged:

    - ``engine_specific_measured``    -- two-sided; the gap was actually observed.
    - ``engine_specific_lower_bound`` -- slow side ran out the clock; gap is >= this.
    - ``ratio_censored``              -- set regardless of the flag, so unresolved
      negatives can be counted rather than silently read as negatives.

    ``engine_specific`` is the union of the two flagged components, so artifacts
    already on disk and consumers keying on it keep reading the same field. Never
    report the union as a single headline number -- it overstates what was measured.
    """
    slowest, fastest = max(ms, key=ms.get), min(ms, key=ms.get)
    # A 0.0ms floor would divide by zero. It is also the STRONGEST possible
    # engine-specific signal (one engine over budget, another unmeasurably fast), so it
    # must not be silently dropped -- record ratio=null and flag on the slowest engine
    # still being over budget.
    ratio = (ms[slowest] / ms[fastest]) if ms[fastest] > 0 else None
    censored = slowest in timed_out
    flagged = len(ms) > 1 and (ratio is None or ratio >= engine_ratio)
    return {
        "slowest_engine": slowest, "fastest_engine": fastest,
        "ratio": ratio,
        "ratio_censored": censored,
        "engine_specific": flagged,
        "engine_specific_measured": flagged and not censored,
        "engine_specific_lower_bound": flagged and censored,
    }


def summarize(confirmed: list) -> dict:
    """Split tally over confirmed rows. ``unresolved`` = censored and UNDER the gate."""
    return {
        "confirmed": len(confirmed),
        "engine_specific": sum(1 for c in confirmed if c.get("engine_specific")),
        "engine_specific_measured": sum(
            1 for c in confirmed if c.get("engine_specific_measured")),
        "engine_specific_lower_bound": sum(
            1 for c in confirmed if c.get("engine_specific_lower_bound")),
        "unresolved_censored": sum(
            1 for c in confirmed
            if c.get("ratio_censored") and not c.get("engine_specific")),
    }
