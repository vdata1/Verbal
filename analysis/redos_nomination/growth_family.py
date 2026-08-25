#!/usr/bin/env python3
r"""Growth curves for ONE regex across engines, on a controlled length family.

WHAT QUESTION THIS ANSWERS
--------------------------
The confirm artifact can only say "engine A was N times slower than engine B on this
string". Per the standard this project already set (HANDOFF_redos_timing.md R5, the
2026-08-03 triage 4b), a constant factor between two engines is NOT a finding about an
engine. What would make it one is a different ALGORITHMIC CLASS, and separating those
needs one shape at growing n -- which unrelated fuzz strings cannot provide, however
many of them agree.

So: build a family, sweep it on every engine, fit the same two models the corpus
nominator fits, and compare the fitted class ACROSS engines rather than the milliseconds.

  same class, different constant  -> not reportable; bun is just quicker here
  different class                 -> reportable: the engines disagree on complexity

WHY A SYNTHETIC FAMILY AND NOT THE CORPUS SEED
----------------------------------------------
`nominate_probe.ladder` cuts a real corpus string down by middle-deletion, which is right
for NOMINATION (it needs no insight into the regex) but wrong here: every rung changes
which characters are present, so the exponent wobbles -- the probe's own classify()
docstring says so, and works around it with the k>6 escape hatch. Comparing two engines'
exponents needs that wobble gone, so the family below is one unit repeated, and the only
thing that changes between rungs is n.

THE FITTER IS NOT REIMPLEMENTED
-------------------------------
`ols` and `classify` are lifted verbatim out of nominate_probe.py at import time, by AST,
rather than copied or re-derived. Copying would let this drift from the validated
classifier (base 2.00 on /(a+)+$/, phi on /(a|aa)+$/, k~2 on /a+b/), and a plain import
is not possible: nominate_probe runs a corpus sweep at module scope. If that file grows a
__main__ guard, replace this with a real import.

Usage:
    python analysis/redos_nomination/growth_family.py --out FILE.json
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(_HERE, "ladder_harness.js")
PROBE = os.path.join(_HERE, "nominate_probe.py")

# Pinned engines, extracted from the image and running natively (HANDOFF_2026-08-11).
# Absolute ms are box-dependent; the fitted CLASS is what travels, which is the whole
# reason this compares curves and not milliseconds.
PINNED = "/scratch/turcotte/pinned_engines/usr/local/bin"
ENGINE_CMD = {
    "node": [f"{PINNED}/node"],
    "bun": [f"{PINNED}/bun"],
    "deno": [f"{PINNED}/deno", "run", "--quiet", "--allow-read"],
    "bun-canary": ["/scratch/turcotte/verbal/engines/bun-linux-x64/bun"],
}


def _lift(*names):
    """Pull top-level defs/assignments out of nominate_probe.py without executing it.

    The thresholds classify() closes over (ABS_FLOOR_MS, POLY_K_MAX, EXP_R2_MIN) are
    lifted too rather than restated here -- restating them is exactly the drift this is
    meant to avoid, and a threshold that disagrees with the validated nominator would
    make these verdicts incomparable with the window sweep's.
    """
    tree = ast.parse(open(PROBE).read())
    picked, seen = [], set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            picked.append(node)
            seen.add(node.name)
        elif isinstance(node, ast.Assign):
            tgt = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(t in names for t in tgt):
                picked.append(node)
                seen.update(t for t in tgt if t in names)
    missing = set(names) - seen
    if missing:
        raise SystemExit(f"nominate_probe.py no longer defines {sorted(missing)}")
    ns = {"math": math}
    exec(compile(ast.Module(picked, []), PROBE, "exec"), ns)
    return [ns[n] for n in names]


ols, classify, _FLOOR, _KMAX, _R2MIN = _lift(
    "ols", "classify", "ABS_FLOOR_MS", "POLY_K_MAX", "EXP_R2_MIN")

# --- the regex under study ---------------------------------------------------------
# regex_14648, the best growth-curve candidate in the 2026-08-07 confirm (triage 6):
# fully measured on both sides, a real match, and bun 13-27x faster on replace/split.
RID = "regex_14648"
PATTERN = r'^(?:[^`"[]+|`[^`]*`|"[^"]*")* AS\s+'

# The ambiguity is branch 1 under the star: a run of n characters that are none of
# ` " [ can be partitioned across star iterations in 2^(n-1) ways, and the engine must
# explore them whenever the tail fails. Both families hold that run at length n and vary
# nothing else.
#   fail  -- tail can never match ` AS\s+`, so the whole search space is explored. The
#            classic ReDoS probe, and the cleanest read on the class.
#   match -- tail DOES match, mirroring the corpus rows in triage 6, which were slow
#            AND returned a real match. Kept because that combination is the odd one and
#            an engine could plausibly differ only here.
#
# WHICH LENGTH AXIS -- measured, not assumed. The confirm's own rows are slow AND return
# a match, and it is worth knowing where that cost lives before fitting anything:
#
#   growing the PREFIX (n copies of the backtick unit) is FLAT: 76-79 ms on node from 66
#   to 281 chars, and instant if the tail cannot match. Prefix length is not the axis.
#
#   growing the TRAILING WHITESPACE doubles the cost per added character, 0.002 ms at
#   n=3 to 2487 ms at n=24, matching throughout. That is the axis: every whitespace char
#   is inside `[^`"[]`, so branch 1 under the star can partition a run of n of them
#   2^(n-1) ways, and the tail ` AS\s+` competes for the same characters.
#
# The real corpus string carries a 19-char whitespace tail and costs 68-79 ms natively,
# which is where the `tail` family sits at n=19 -- so this family is that string's own
# shape, parameterized.
PREFIX = '\\`zgl*\\`"J"\\`hzUZM\\`\\`p.f\\=qvdX\\`\\`Ad4Dqr\\`'   # verbatim, replace #26
FAMILIES = {
    # Classic ReDoS probe: an ambiguous run with a tail that can never match.
    "fail": lambda n: "a" * n + " AX",
    # Ambiguous run, MATCHING tail. Reads SAFE everywhere -- kept because that is the
    # result that proves run length is not what triage 6's rows were measuring.
    "match": lambda n: "a" * n + " AS\t",
    # Negative control: the corpus prefix repeated, tail held fixed. Flat in n.
    "prefix": lambda n: PREFIX * n + "  AS\x0b\r\n\t",
    # The corpus shape, on the axis that actually drives it.
    "tail": lambda n: PREFIX + "  AS" + "\t" * n,
}
NS = list(range(1, 41))
APIS = ["test", "replace", "split", "match"]

# Known-answer controls, with the analytic result each one must reproduce. They exist to
# falsify the HARNESS, not the regexes: `ladder_harness.js` grew an `api` switch to run
# this study, and a sweep that quietly measured the wrong thing afterwards would look
# exactly like a clean result. Run with --controls; the expected column is the analytic
# answer, and these same three are what validated the nominator originally.
CONTROLS = [
    ("(a+)+$", lambda n: "a" * n + "!", "EXPONENTIAL", "base ~2.0"),
    ("(a|aa)+$", lambda n: "a" * n + "!", "EXPONENTIAL", "base ~1.618 (phi)"),
    ("a+b", lambda n: "a" * n, None, "polynomial, k~2"),
]


def sweep(engine, api, inputs, stop_ms, per_rung_ms, spec_path, pattern=PATTERN):
    with open(spec_path, "w") as f:
        json.dump({"pattern": pattern, "flags": "", "inputs": inputs, "api": api,
                   "stop_ms": stop_ms, "per_rung_ms": per_rung_ms}, f)
    try:
        p = subprocess.run(ENGINE_CMD[engine] + [HARNESS, spec_path],
                           capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "harness wall-clock (180s)"}
    for line in p.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and "ok" in o:
            return o
    return {"ok": False, "error": (p.stderr or "no output").strip()[:200]}


def fits(res):
    """The two fitted models behind classify()'s verdict, so curves can be COMPARED and
    not just labelled. Same usable-point cut as classify, for the same reason."""
    if not res.get("ok"):
        return None
    base, pts = res.get("baseline_ms"), res.get("points") or []
    usable = [p for p in pts if base and p["ms"] >= 10 * base]
    if len(usable) < 3:
        return None
    xs = [p["len"] for p in usable]
    ys = [math.log(p["ms"]) for p in usable]
    e, q = ols(xs, ys), ols([math.log(x) for x in xs], ys)
    if not e or not q:
        return None
    return {"exp_base": math.exp(e[0]), "exp_r2": e[2], "poly_k": q[0], "poly_r2": q[2],
            "n_lo": xs[0], "n_hi": xs[-1], "rungs": len(xs),
            "dearest_ms": usable[-1]["ms"],
            "matched": bool(usable[-1].get("value"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default="node,deno,bun,bun-canary")
    ap.add_argument("--apis", default=",".join(APIS))
    ap.add_argument("--families", default=",".join(FAMILIES))
    ap.add_argument("--stop-ms", type=float, default=20.0)
    ap.add_argument("--per-rung-ms", type=int, default=3000)
    ap.add_argument("--out", default=None)
    ap.add_argument("--controls", action="store_true",
                    help="sweep the known-answer regexes instead; the harness grew an "
                         "api switch for this study, and these are what catch it if the "
                         "switch made the sweep measure the wrong thing")
    a = ap.parse_args()

    spec_path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "growth_family_spec.json")

    if a.controls:
        bad = 0
        for pat, mk, want, note in CONTROLS:
            inputs = [mk(n) for n in NS]
            for api in a.apis.split(","):
                for e in a.engines.split(","):
                    res = sweep(e, api, inputs, a.stop_ms, a.per_rung_ms, spec_path, pat)
                    verdict, _ = classify(res)
                    f = fits(res)
                    ok = (want is None or verdict == want)
                    bad += 0 if ok else 1
                    shape = (f"b={f['exp_base']:.3f} k={f['poly_k']:.2f}" if f else "-")
                    print(f"{'OK ' if ok else 'BAD'} /{pat}/ {api:8} {e:11} "
                          f"{verdict:13} {shape}   expect {want or '-'} ({note})",
                          flush=True)
        print(f"\ncontrols: {'all as expected' if not bad else f'{bad} UNEXPECTED'}")
        return 1 if bad else 0
    # Box provenance: absolute ms here are meaningless off this machine, and a curve
    # measured under load is the 521ms-phantom trap one level up (HANDOFF_2026-08-11).
    # The fitted BASE is what travels; record the conditions so a reader can see whether
    # the milliseconds behind it were taken on a quiet box.
    try:
        load = list(os.getloadavg())
    except OSError:
        load = None
    out = {"regex_id": RID, "pattern": PATTERN, "ns": [NS[0], NS[-1]],
           "stop_ms": a.stop_ms, "per_rung_ms": a.per_rung_ms,
           "box": {"hostname": __import__("socket").gethostname(),
                   "cpus": os.cpu_count(), "loadavg_at_start": load,
                   "engines": "pinned, extracted from the image; native, no docker"},
           "engine_versions": {}, "runs": []}

    for e in a.engines.split(","):
        # argv[0] only: deno's is `deno run ...`, and `deno run --version` prints nothing.
        v = subprocess.run([ENGINE_CMD[e][0], "--version"], capture_output=True, text=True)
        out["engine_versions"][e] = v.stdout.strip().split("\n")[0]

    for fam in a.families.split(","):
        inputs = [FAMILIES[fam](n) for n in NS]
        for api in a.apis.split(","):
            for e in a.engines.split(","):
                res = sweep(e, api, inputs, a.stop_ms, a.per_rung_ms, spec_path)
                verdict, detail = classify(res)
                row = {"family": fam, "api": api, "engine": e,
                       "verdict": verdict, "detail": detail,
                       "hung": bool(res.get("hung")), "hung_len": res.get("hung_len"),
                       "fit": fits(res), "points": res.get("points") or []}
                out["runs"].append(row)
                f = row["fit"]
                shape = (f"b={f['exp_base']:.3f} R2={f['exp_r2']:.4f} | "
                         f"k={f['poly_k']:.2f} R2={f['poly_r2']:.4f} | "
                         f"n<={f['n_hi']} dearest={f['dearest_ms']:.2f}ms"
                         if f else "-")
                print(f"{fam:6} {api:8} {e:11} {verdict:13} {shape}", flush=True)

    if a.out:
        with open(a.out, "w") as fh:
            json.dump(out, fh, indent=2)
        print(f"\n-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
