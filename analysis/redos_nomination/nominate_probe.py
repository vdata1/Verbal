"""Ladder-based ReDoS nomination, measured against the REAL corpus.

The method is settled (micro_probe.py): a growth curve fitted from ~20-char inputs
classifies a regex's complexity class in milliseconds, recovering base 2.00 on
/(a+)+$/ and phi on /(a|aa)+$/. What is NOT settled is whether the ingredients exist
in practice -- so this runs the whole nomination end-to-end on the recorded 6000-9999
artifacts and measures the hit rate.

The pipeline, per regex:

  1. Read the recorded fuzz strings (results-run-6000-9999/<rid>/test.strings.jsonl).
  2. Mutate them with the REAL pipeline.chaos, at the real config's ops/alphabet/seed.
     Not a re-implementation -- if chaos cannot reach the boundary, this must show it.
  3. Keep the NON-MATCHING mutants. A matching input never backtracks (the same regex
     on a matching string is measurably free), so a matching seed can only ever produce
     a flat curve. This is the step that makes chaos load-bearing rather than incidental.
  4. Seed = the longest non-matching mutant. Longest spans the widest band. Uniform
     rule, no per-regex branching (CLAUDE.md's cardinal rule).
  5. Ladder = middle-deletion rungs of that seed, length 1..len(seed), ascending.
     Preserves both ends -- whatever prefix/suffix forces the failure survives while
     the run in the middle shrinks -- and needs no pump identification. Demonstrated on
     regex_3910's raw fuzzer string: base 1.989, R2 0.9999.
  6. Sweep the ladder in one process per (regex, engine); fit; classify.

THE ORACLE MUST BE BOUNDED. Step 3 asks "does this mutant match", and the obvious
oracle -- Python's re.search -- is itself a backtracking engine. On a ReDoS-prone
corpus regex fed a pathological non-matching mutant, re.search backtracks
catastrophically IN PROCESS, where the sweep's subprocess timeout cannot reach it. An
unbounded oracle wedged the first full run for hours on three real corpus rows:
regex_6580 (#define\s+(\S+)+\s+(\S+) -- the same regex 930c43b's generate oracle bound
was written for), regex_7984 (an email ReDoS), regex_9577 (^(\.?\w+)*$). So each
search is bounded by SIGALRM.

An oracle TIMEOUT is not a problem to swallow -- it is the strongest seed signal there
is. Catastrophic backtracking in re happens precisely when the input does NOT match
(the engine exhausts every partition before giving up), so a timed-out mutant is both
non-matching AND already proven pathological for one backtracking engine. It goes
straight to the front of the seed queue.

Nothing here runs a JS input costing more than STOP_MS, and no oracle call runs longer
than ORACLE_MS. The sweep cannot hang.
"""
import argparse
import glob
import json
import math
import os
import re
import signal
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
sys.path.insert(0, "/repo/src")

from pipeline.chaos import mutants, rng_for  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "ladder_harness.js")
SPEC = "/tmp/ladder_spec.json"
ENGINE_CMD = {"node": ["node"], "bun": ["bun"],
              "deno": ["deno", "run", "--quiet", "--allow-read"]}

# Mirrors config/fullcorpus.yaml. Read rather than hardcoded would be better in the
# real thing; here it keeps the probe standalone.
CHAOS_OPS = ("delete", "insert", "substitute", "duplicate", "transpose",
             "case_flip", "truncate")
CHAOS_ALPHABET = tuple("abcXYZ019 _-.!@#/\\\t\n")
CHAOS_N = 2
SEED = 20260716
ORACLE_MS = 200            # per-search wall-clock bound on the Python-re match oracle


class _OracleTimeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise _OracleTimeout()


signal.signal(signal.SIGALRM, _on_alarm)


def matches_bounded(rx, s):
    """(matched, timed_out). SIGALRM bounds the search: re is a backtracking engine, and
    a pathological non-matching input makes it blow up in-process. A timeout is NOT an
    error here -- it means re backtracks catastrophically on `s`, i.e. `s` is a proven
    pathological non-matching input. Single-threaded only (SIGALRM); this probe is."""
    signal.setitimer(signal.ITIMER_REAL, ORACLE_MS / 1000)
    try:
        return bool(rx.search(s)), False
    except _OracleTimeout:
        return False, True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def mid_delete(s: str, L: int) -> str:
    """`s` cut to L chars by deleting from the MIDDLE, preserving both ends."""
    a, b = (L + 1) // 2, L // 2
    return s[:a] + (s[len(s) - b:] if b else "")


def ladder(seed: str, max_rungs: int = 60) -> list:
    """Ascending middle-deletion rungs. Subsampled evenly if the seed is long: the
    sweep stops early on anything exponential, so the rung count only bites on the
    safe regexes, where it is pure cost."""
    n = len(seed)
    if n <= max_rungs:
        Ls = range(1, n + 1)
    else:
        step = n / max_rungs
        Ls = sorted({max(1, int(1 + i * step)) for i in range(max_rungs)} | {n})
    return [mid_delete(seed, L) for L in Ls]


def ols(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    icept = my - slope * mx
    sst = sum((y - my) ** 2 for y in ys)
    ssr = sum((y - (icept + slope * x)) ** 2 for x, y in zip(xs, ys))
    return slope, icept, (1 - ssr / sst if sst > 0 else 1.0)


def sweep(engine, pattern, flags, inputs):
    with open(SPEC, "w") as f:
        json.dump({"pattern": pattern, "flags": flags, "inputs": inputs}, f)
    try:
        p = subprocess.run(ENGINE_CMD[engine] + [HARNESS, SPEC],
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "harness wall-clock"}
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
    return {"ok": False, "error": (p.stderr or "no output").strip()[:120]}


ABS_FLOOR_MS = 1.0    # a super-linear NOMINATION must clear the sub-ms timer-noise floor
POLY_K_MAX = 6        # a power law needing degree > this over our band is exp masquerading
EXP_R2_MIN = 0.95     # ...but the exp fit must still be genuinely good to call EXPONENTIAL


def classify(res):
    """(verdict, detail). Fits only where the signal clears the call overhead by 10x --
    below that the curve measures the cost of calling test(), not of searching. A hung
    rung (the engine itself backtracking past the harness's per-rung bound) short-circuits
    to HANG: an engine that wedges on a short input is the strongest signal there is."""
    if not res.get("ok"):
        return "ERROR", res.get("error", "?")
    if res.get("hung"):
        return "HANG", f"engine backtracks past the per-rung bound on a " \
                       f"{res.get('hung_len')}-char input (strongest ReDoS signal)"
    base, pts = res["baseline_ms"], res["points"]
    usable = [p for p in pts if p["ms"] >= 10 * base]
    if len(usable) < 3:
        return "SAFE", f"never reached 10x call overhead over {len(pts)} rungs"
    xs = [p["len"] for p in usable]
    ys = [math.log(p["ms"]) for p in usable]
    e, q = ols(xs, ys), ols([math.log(x) for x in xs], ys)
    if not e or not q:
        return "SAFE", "degenerate fit"
    b, k = math.exp(e[0]), q[0]
    dearest = usable[-1]["ms"]

    # EXPONENTIAL, two ways in, BOTH gated by an ABSOLUTE COST FLOOR. The 10x-overhead cut
    # above is RELATIVE to the call cost and still sits deep in sub-microsecond timer
    # noise; an exponential fit down there measures jitter, not searching. So an
    # EXPONENTIAL nomination is trusted only if the dearest measured rung actually left the
    # noise floor -- which kills the base~1.10-at-0.001ms false positives (regex_8206,
    # 8848). The floor is deliberately NOT applied to POLYNOMIAL/UNCLASSIFIED: a genuine
    # quadratic can be real ReDoS while still cheap at these seed lengths, and those
    # buckets are the untriaged signal, not a promotion. The two ways in:
    #  (a) exp beats poly outright -- the clean, wide-band case (the a+ / 3910 controls).
    #  (b) exp fits well AND the only competing poly needs an ABSURD degree (k > 6). A
    #      middle-deletion ladder on a heterogeneous corpus seed wobbles the exponent
    #      (different chars leave at each rung), so a high-degree poly can edge out R2 --
    #      but a degree->6+ power law over this narrow band IS the exponential in disguise.
    #      regex_6580 (k=10) and regex_9577 (k=17) land here; a real polynomial sits at
    #      k<=6 and never trips this, so the POLYNOMIAL bucket is untouched.
    if b >= 1.1 and dearest >= ABS_FLOOR_MS and (
            (e[2] >= 0.99 and e[2] > q[2]) or
            (e[2] >= EXP_R2_MIN and k > POLY_K_MAX)):
        return "EXPONENTIAL", f"base {b:.3f} R2 {e[2]:.4f} on {len(xs)} rungs " \
                              f"(len {xs[0]}..{xs[-1]}, dearest {dearest:.2f}ms, poly k={k:.1f})"
    if q[2] >= 0.99 and k <= POLY_K_MAX and q[2] > e[2]:
        kind = "POLYNOMIAL" if k >= 1.5 else "LINEAR"
        return kind, f"k {k:.2f} R2 {q[2]:.4f} on {len(xs)} rungs (dearest {dearest:.2f}ms)"
    return "UNCLASSIFIED", f"exp b={b:.2f} R2 {e[2]:.4f} | poly k={k:.2f} R2 {q[2]:.4f} " \
                           f"(dearest {dearest:.2f}ms)"


ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=200)
ap.add_argument("--engines", default="node")
ap.add_argument("--window", default="/repo/results-run-6000-9999")
ap.add_argument("--dump-nominees", default=None,
                help="write every notable verdict (rid+seed+pattern+detail) as JSONL, "
                     "the shortlist dev_confirm.py's confirm pass consumes.")
args = ap.parse_args()
engines = args.engines.split(",")

# --- Positive controls, through the IDENTICAL ladder->sweep->classify path ----------
# Without these a run of SAFE verdicts is unfalsifiable: a nominator that is simply
# broken reports exactly the same thing as a corpus with no vulnerable regexes. The
# first control is the load-bearing one -- a REAL corpus regex fed its REAL fuzzer
# string (from notable_results/node_redos/regex_3910_size_analysis.js, whose 5s/11s/22s
# ladder was measured by hand), so it exercises the mid_delete ladder on exactly the
# kind of heterogeneous random string the corpus actually produces.
P3910 = r'''(?:\b[a-z\d](?:[_.:+]?[a-z\d]+)*_?_|`[^`]+`_?_|_`[^`]+`)(?=[\s\-.,:;!?\\\/'")\]}]|$)'''
S3910 = "le0i1xoa2bbhey0vg79f2mtujiqktmqt5gqwpa9g49vet63zwun2ancc0z87p_#}]"

CONTROLS = [
    ("regex_3910 raw fuzzer string", P3910, "g", S3910, "EXPONENTIAL"),
    ("/(a+)+$/ non-matching seed", r"(a+)+$", "", "a" * 40 + "!", "EXPONENTIAL"),
    ("/(a+)+$/ MATCHING seed", r"(a+)+$", "", "a" * 40, "SAFE"),
    ("/^a+$/ non-matching seed", r"^a+$", "", "a" * 40 + "!", "SAFE"),
]

print("=" * 78)
print("CONTROLS (same ladder -> sweep -> classify path as the corpus below)")
ctl_ok = True
for name, pat, fl, seed_s, expect in CONTROLS:
    v, detail = classify(sweep(engines[0], pat, fl, ladder(seed_s)))
    ok = (v == expect)
    ctl_ok &= ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<32} -> {v:<13} (want {expect})")
    print(f"        {detail}")
if not ctl_ok:
    print("\n!! A CONTROL FAILED -- the corpus verdicts below are not trustworthy.\n")

files = sorted(glob.glob(f"{args.window}/*/test.strings.jsonl"))[:args.limit]
stats = {"regexes": 0, "no_py_compile": 0, "no_nonmatching_mutant": 0, "swept": 0,
         "oracle_timeouts": 0, "regexes_w_oracle_to": 0}
verdicts = {}
hits = []

for path in files:
    rid = path.split("/")[-2]
    meta, fuzz = None, []
    for line in open(path):
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("kind") == "meta":
            meta = o
        elif o.get("kind") == "string":
            fuzz.append(o["string"])
    if not meta or not fuzz:
        continue
    stats["regexes"] += 1
    pattern, flags = meta["pattern"], meta.get("flags", "")

    # The oracle for "does this mutant still match". The pipeline records py_re_matches
    # for fuzz strings via its transpiler; this prototype uses raw `re`, which is why a
    # JS-only construct simply skips the regex. Counted, not hidden.
    try:
        rx = re.compile(pattern)
    except re.error:
        stats["no_py_compile"] += 1
        continue

    seen = set(fuzz)
    nonmatching = []            # (mutant, oracle_timed_out) -- second flag prioritises seeds
    had_to = False
    for i, s in enumerate(fuzz):
        rng = rng_for(SEED, rid, "test", i)
        for m, label in mutants(s, CHAOS_N, rng, CHAOS_OPS, CHAOS_ALPHABET, seen):
            seen.add(m)
            matched, timed_out = matches_bounded(rx, m)
            if timed_out:
                stats["oracle_timeouts"] += 1
                had_to = True
            if not matched:                     # a timeout counts as non-matching
                nonmatching.append((m, timed_out))
    if had_to:
        stats["regexes_w_oracle_to"] += 1
    if not nonmatching:
        stats["no_nonmatching_mutant"] += 1
        continue

    # Seed selection, uniform: prefer a mutant that already blew the oracle -- it is a
    # proven pathological non-matching input for a backtracking engine -- and among ties
    # take the longest, which spans the widest band. Falls through to plain longest when
    # no mutant timed out.
    seed_s = max(nonmatching, key=lambda mt: (mt[1], len(mt[0])))[0]
    rungs = ladder(seed_s)
    stats["swept"] += 1
    for engine in engines:
        v, detail = classify(sweep(engine, pattern, flags, rungs))
        verdicts[v] = verdicts.get(v, 0) + 1
        if v in ("HANG", "EXPONENTIAL", "POLYNOMIAL", "UNCLASSIFIED"):
            # Carry the seed too: it is the expensive thing this loop derives (the bounded
            # oracle pass), and the confirm pass needs it verbatim to grow long inputs.
            hits.append({"verdict": v, "engine": engine, "rid": rid, "pattern": pattern,
                         "flags": flags, "seed": seed_s, "seed_len": len(seed_s),
                         "detail": detail})

print(f"\n{'=' * 78}\nregexes read: {stats['regexes']}   swept: {stats['swept']}")
print(f"  skipped, pattern not python-compilable : {stats['no_py_compile']}")
print(f"  skipped, chaos made no non-matching mutant: {stats['no_nonmatching_mutant']}")
print(f"  oracle SIGALRM timeouts: {stats['oracle_timeouts']} mutants across "
      f"{stats['regexes_w_oracle_to']} regexes (each an in-process re backtrack -- "
      f"would have wedged an unbounded oracle)")
print(f"\nverdicts ({','.join(engines)}): " +
      "  ".join(f"{k}={v}" for k, v in sorted(verdicts.items())))
if hits:
    print(f"\n{'=' * 78}\nNOMINATED / notable:")
    for h in sorted(hits, key=lambda h: (h["verdict"], h["engine"], h["rid"])):
        print(f"  [{h['verdict']}] {h['rid']} on {h['engine']}  (seed {h['seed_len']} chars)")
        print(f"      /{h['pattern'][:90]}/")
        print(f"      {h['detail']}")

if args.dump_nominees:
    with open(args.dump_nominees, "w") as f:
        for h in hits:
            f.write(json.dumps(h) + "\n")
    npoly = sum(h["verdict"] in ("POLYNOMIAL", "UNCLASSIFIED") for h in hits)
    print(f"\nwrote {len(hits)} nominees ({npoly} POLYNOMIAL/UNCLASSIFIED to confirm) "
          f"-> {args.dump_nominees}")
