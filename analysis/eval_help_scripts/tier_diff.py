#!/usr/bin/env python3
r"""JIT-vs-interpreter differential: run one engine against ITSELF at two tiers.

WHY THIS IS DIFFERENT FROM THE CROSS-ENGINE DIFF
------------------------------------------------
The cross-engine oracle has a structural ceiling this project has documented for months:
node and deno both embed V8, so "2 of 3 engines agree" is one implementation agreeing with
itself, and no vote can settle which side is right without a spec argument.

Running ONE engine at two optimization tiers has neither problem:

  * If an engine's JIT and its own interpreter disagree, **exactly one of them is wrong**,
    by construction. No majority, no spec reasoning, no reference implementation.
  * The finding is a single-vendor bug report with a crisp repro, and "disabling the
    RegExp JIT fixes it" is the most actionable sentence a maintainer can receive.
  * It finds JIT MISCOMPILES, which are the highest-severity class -- and, because they
    are optimization-dependent, are exactly the bugs a conformance suite misses.

Demonstrated on first contact (2026-08-03): the v-mode class-union bug
`/[\s\t\p{C}]/v` on U+E8541 returns a lone surrogate under bun's Yarr JIT and the correct
whole code point with `BUN_JSC_useRegExpJIT=0`, localizing it to the JIT. The sticky-`.*`
and `lastIndex`-surrogate bugs reproduce under both tiers, placing them elsewhere -- so the
tier axis both FINDS and LOCALIZES.

THE MOST VALUABLE INPUT IS A CASE THE ENGINES AGREED ON
-------------------------------------------------------
A tier disagreement on a case where all three engines agreed is a bug **no cross-engine
differential could ever have found**. So `--sample` deliberately draws from all harnesses
the pipeline has already generated, not from the headline's discrepancy list. The harnesses
already exist -- this costs engine time only, no generation.

TIERS
-----
  node  --regexp-interpret-all                      (V8: skip the regexp JIT entirely)
  deno  --v8-flags=--regexp-interpret-all           (same V8 knob, through deno)
  bun   BUN_JSC_useRegExpJIT=0                      (JSC: env var, no argv equivalent)

Verified to take effect, not be silently accepted: a timing loop goes 1ms -> 59ms on bun,
1ms -> 4ms on node, 1ms -> 5ms on deno.

USAGE
-----
  tier_diff.py --sample 400 --results-root results
  tier_diff.py --harness results/regex_14680/exec__0__v.js
  tier_diff.py --regex regex_14680 --results-root results
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "eval"))

import run_eval                                    # noqa: E402
from run_eval import ENGINE_CMD, ENGINE_ENV, run_engine   # noqa: E402

# --- Tier registry -----------------------------------------------------------
# Each entry registers a PSEUDO-ENGINE into the runner's own tables, so `run_engine`,
# `_comparable`, timeouts and defect classification all apply with no special-casing.
TIERS: dict[str, dict] = {
    "node": {
        "baseline": "node",
        "variant": "node_interp",
        "cmd": ["node", "--regexp-interpret-all"],
        "env": {},
        "note": "V8 regexp interpreter (no regexp JIT)",
    },
    "deno": {
        "baseline": "deno",
        "variant": "deno_interp",
        "cmd": ["deno", "run", "--quiet", "--v8-flags=--regexp-interpret-all"],
        "env": {},
        "note": "V8 regexp interpreter, via deno's --v8-flags",
    },
    "bun": {
        "baseline": "bun",
        "variant": "bun_nojit",
        "cmd": ["bun"],
        "env": {"BUN_JSC_useRegExpJIT": "0"},
        "note": "JavaScriptCore with the Yarr RegExp JIT disabled",
    },
}

for _spec in TIERS.values():
    ENGINE_CMD[_spec["variant"]] = _spec["cmd"]
    if _spec["env"]:
        ENGINE_ENV[_spec["variant"]] = _spec["env"]


def check_harness(path: str, engines: list[str]) -> list[dict]:
    """Run each engine at both tiers over one harness; report intra-engine disagreements."""
    findings = []
    for base in engines:
        spec = TIERS[base]
        variant = spec["variant"]
        a = run_engine(base, path)
        b = run_engine(variant, path)

        # A tier that TIMED OUT is not a disagreement -- the interpreter is legitimately
        # slower (measured 59x on bun), so a case near the budget can time out at one tier
        # and finish at the other. That is a performance fact, reported separately; calling
        # it a miscompile would flood the output with false positives on ReDoS-ish inputs.
        if a["timed_out"] or b["timed_out"]:
            findings.append({
                "harness": path, "engine": base, "kind": "tier_timeout",
                "timed_out": [t for t, r in ((base, a), (variant, b)) if r["timed_out"]],
            })
            continue

        # A defect at one tier only is worth surfacing: a crash the other tier does not
        # have is still a single-engine bug, just not a value miscompile.
        if a["defect"] or b["defect"]:
            findings.append({
                "harness": path, "engine": base, "kind": "tier_defect",
                "defect": [t for t, r in ((base, a), (variant, b)) if r["defect"]],
            })
            continue

        if a["comparable"] != b["comparable"]:
            findings.append({
                "harness": path, "engine": base, "kind": "tier_value_disagreement",
                "jit": a["comparable"], "interp": b["comparable"],
            })
    return findings


def _harness_pattern(path: str) -> str | None:
    """The regex source a harness was built for, read from its own `const pattern = ...`.

    The harness IS the artifact -- reading the pattern out of it needs no sibling
    diff.json and stays correct even for a directory whose eval never ran.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("const pattern = "):
                    return json.loads(line[len("const pattern = "):].rstrip().rstrip(";"))
                if line.startswith("const flags = "):
                    return None            # past the pattern line; not found
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _harness_paths(args) -> list[str]:
    """Select harnesses, optionally STRATIFIED by flags and by pattern construct.

    Why stratification is not a nicety: a uniform sweep of 600 harnesses found zero tier
    disagreements even though ~76 of them carried `v` (v-mode is 12.7% of the corpus's
    harnesses). The known JIT miscompile needs a CONJUNCTION -- a v-mode class union over
    several operands including a property escape, against an astral input -- and uniform
    sampling over the whole corpus is badly underpowered for conjunctions. Targeting the
    stratum where a bug class lives is the difference between a sweep that can find it and
    one that cannot (EXPANSION_IDEAS_2026-08-03.md, section 5).
    """
    if args.harness:
        return list(args.harness)
    root = args.results_root
    dirs = [os.path.join(root, args.regex)] if args.regex else sorted(
        glob.glob(os.path.join(root, "regex_*")))

    # Directory-level pattern filter first: one file read per regex, not per harness.
    if args.pattern_contains:
        kept = []
        for d in dirs:
            probe = next(iter(sorted(glob.glob(os.path.join(d, "*__*__*.js")))), None)
            if probe is None:
                continue
            src = _harness_pattern(probe)
            if src is not None and args.pattern_contains in src:
                kept.append(d)
        dirs = kept

    paths = []
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*__*__*.js")):
            if args.flags_contains:
                flags = os.path.basename(f).rsplit("__", 1)[1][:-3]
                if not all(ch in flags for ch in args.flags_contains):
                    continue
            paths.append(f)
    paths.sort()

    if args.sample and len(paths) > args.sample:
        # Seeded so a reported sweep is reproducible; the sample IS the experiment.
        random.Random(args.seed).shuffle(paths)
        paths = sorted(paths[:args.sample])
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--harness", nargs="*", help="explicit harness .js paths")
    ap.add_argument("--results-root", default="results")
    ap.add_argument("--regex", help="restrict to one regex_<id> directory")
    ap.add_argument("--sample", type=int, help="random sample size over all harnesses")
    ap.add_argument("--flags-contains", default=None,
                    help="only harnesses whose flag set contains ALL these chars (e.g. 'v')")
    ap.add_argument("--pattern-contains", default=None,
                    help="only regexes whose SOURCE contains this substring (e.g. '\\p{')")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--engines", default="node,bun,deno",
                    help="base engines to tier-check (each runs twice)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what the selection covers and exit -- no engine runs")
    ap.add_argument("--out")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    for e in engines:
        if e not in TIERS:
            sys.exit(f"no tier variant defined for engine {e!r} "
                     f"(have: {', '.join(sorted(TIERS))})")

    paths = _harness_paths(args)
    if not paths:
        sys.exit("no harnesses matched -- check --results-root / --regex")

    # Breadth, not just volume. 25 disagreements sounds like a sweep found a lot; if all
    # 25 sit in one regex_<id> it found ONE already-known bug 25 times. Reporting distinct
    # regexes alongside harness count is what makes a sweep result readable at all -- and
    # what says whether a null means "nothing there" or "never looked broadly enough".
    covered = sorted({os.path.basename(os.path.dirname(p)) for p in paths})
    print(f"tier-checking {len(paths)} harnesses across {len(covered)} distinct regexes "
          f"x {len(engines)} engines ({len(paths) * len(engines) * 2} engine runs)",
          flush=True)
    if args.dry_run:
        print(f"  regexes: {', '.join(covered[:12])}"
              f"{' ...' if len(covered) > 12 else ''}")
        per = len(paths) / max(len(covered), 1)
        print(f"  mean harnesses per regex: {per:.1f}")
        print("  (dry run -- no engines executed)")
        return
    for e in engines:
        print(f"  {e:5} baseline={TIERS[e]['baseline']:5} "
              f"variant={TIERS[e]['variant']:12} [{TIERS[e]['note']}]", flush=True)

    t0 = time.monotonic()
    findings: list[dict] = []
    for i, path in enumerate(paths, 1):
        got = check_harness(path, engines)
        for f in got:
            if f["kind"] == "tier_value_disagreement":
                print(f"  !! TIER DISAGREEMENT {f['engine']}: {os.path.relpath(path)}",
                      flush=True)
                print(f"       jit    {f['jit'][:150]}", flush=True)
                print(f"       interp {f['interp'][:150]}", flush=True)
            elif args.verbose:
                print(f"  .  {f['kind']} {f['engine']}: {os.path.relpath(path)}", flush=True)
        findings.extend(got)
        if args.verbose and i % 50 == 0:
            print(f"  ... {i}/{len(paths)} ({time.monotonic() - t0:.0f}s)", flush=True)

    elapsed = time.monotonic() - t0
    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1

    out = {
        "harnesses_checked": len(paths),
        "distinct_regexes_checked": len(covered),
        "engines": engines,
        "tiers": {e: TIERS[e] for e in engines},
        "sample": args.sample,
        "seed": args.seed,
        "counts": by_kind,
        "value_disagreements": [f for f in findings
                                if f["kind"] == "tier_value_disagreement"],
        "other": [f for f in findings if f["kind"] != "tier_value_disagreement"],
        "elapsed_s": round(elapsed, 1),
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    print("=" * 60)
    print(f"harnesses checked:      {len(paths)}  across {len(covered)} distinct regexes")
    hit_rids = sorted({os.path.basename(os.path.dirname(f["harness"]))
                       for f in findings if f["kind"] == "tier_value_disagreement"})
    if hit_rids:
        print(f"  disagreements span {len(hit_rids)} regex(es): {', '.join(hit_rids[:8])}")
    print(f"TIER DISAGREEMENTS:     {by_kind.get('tier_value_disagreement', 0)}"
          "   [each is a definite bug in that one engine]")
    print(f"tier timeouts:          {by_kind.get('tier_timeout', 0)}"
          "   [interpreter is slower; not a miscompile]")
    print(f"tier defects:           {by_kind.get('tier_defect', 0)}")
    print(f"elapsed:                {elapsed:.0f}s")
    if args.out:
        print(f"-> {args.out}")


if __name__ == "__main__":
    main()
