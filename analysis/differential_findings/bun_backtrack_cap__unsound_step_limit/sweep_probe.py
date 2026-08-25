"""Method-validation probe for the ReDoS length axis (HANDOFF_redos_timing.md #4).

Question: can a timing-vs-length curve classify a regex's complexity class from the
CHEAP regime, without ever paying for a long execution?

Not integrated with the pipeline on purpose -- this validates or kills the method
before any length-family work is designed into generate/chaos.

The band search is the whole trick. Measurements are only informative between the
noise floor and a small budget, so bracket that band by binary search and sweep
inside it. Everything below the floor is noise; everything above the budget is a
question we already know we cannot afford to ask.

Monotonicity of t(n) is assumed by the binary searches. That is a real assumption --
an engine with a backtracking step limit breaks it by flattening at large n -- and a
knee in the printed points is what that looks like.
"""
import base64, json, math, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "sweep_harness.js")

# --allow-read is a probe-only deviation from the pipeline's ENGINE_CMD: the spec now
# arrives as a file because argv blows ARG_MAX on the 100k-char safe-case controls.
ENGINE_CMD = {"node": ["node"], "bun": ["bun"],
              "deno": ["deno", "run", "--quiet", "--allow-read"]}
SPEC_PATH = "/tmp/sweep_spec.json"

FLOOR_MS = 1.0        # below this, timer noise dominates -- the method's real weakness
BUDGET_MS = 2000.0    # deliberately far under the pipeline's 20s: the point is to never pay it
REPEATS = 3           # min-of-k; timing noise is one-sided (contention only ever adds)
N_POINTS = 10

# --- the corpus case: analysis/notable_results/node_redos/regex_3910_size_analysis.js
# That file records, by hand: "l"+"e"*26+"_#}]" = 5s, *27 = 11s, *28 = 22s (base ~2).
P3910 = r'''(?:\b[a-z\d](?:[_.:+]?[a-z\d]+)*_?_|`[^`]+`_?_|_`[^`]+`)(?=[\s\-.,:;!?\\\/'")\]}]|$)'''
S3910 = "le0i1xoa2bbhey0vg79f2mtujiqktmqt5gqwpa9g49vet63zwun2ancc0z87p_#}]"


def mid_delete(L: int) -> str:
    """The raw fuzzer string cut to L chars by deleting from the MIDDLE.

    Uniform: no pump identification, no per-regex logic, no grammar. Preserves both
    ends, so whatever prefix/suffix forces the failure survives while the run in the
    middle shrinks. If this reproduces the hand-built family's curve, a length axis is
    reachable from a string the fuzzer already found.
    """
    a, b = (L + 1) // 2, L // 2
    return S3910[:a] + (S3910[len(S3910) - b:] if b else "")


CASES = [
    dict(name="regex_3910 -- hand-built pump 'l'+'e'*n+'_#}]'  [GROUND TRUTH]",
         pattern=P3910, flags="g", make=lambda n: "l" + "e" * n + "_#}]",
         lo=1, hi=40, engines=["node"],
         expect="exponential base~2; must reproduce the recorded 5s/11s/22s at n=26/27/28"),
    dict(name="regex_3910 -- MIDDLE-DELETION ladder from the raw fuzzer string  [THE TEST]",
         pattern=P3910, flags="g", make=mid_delete,
         lo=5, hi=len(S3910), engines=["node"],
         expect="exponential IF a length axis is reachable with no human insight"),
    dict(name="/(a+)+$/ vs 'a'*n+'!'  [THE BUN QUESTION]",
         pattern=r"(a+)+$", flags="", make=lambda n: "a" * n + "!",
         lo=1, hi=40, engines=["node", "bun", "deno"],
         expect="is bun exponential-with-a-better-constant, or genuinely not blowing up?"),
    dict(name="/(a+)+$/ vs 'a'*n  (MATCHES -- control)",
         pattern=r"(a+)+$", flags="", make=lambda n: "a" * n,
         lo=1, hi=100000, engines=["node", "bun", "deno"],
         expect="safe: SAME regex, no blowup -- catches 'longer string = slower = ReDoS'"),
    dict(name="/^a+$/ vs 'a'*n+'!'  (negative control)",
         pattern=r"^a+$", flags="", make=lambda n: "a" * n + "!",
         lo=1, hi=200000, engines=["node"], expect="safe"),
    dict(name="/a+b/ vs 'a'*n  (polynomial)",
         pattern=r"a+b", flags="", make=lambda n: "a" * n,
         lo=1, hi=50000, engines=["node"], expect="quadratic, k~2 -- the case yes/no misses"),
]


def measure_once(engine, pattern, flags, inp):
    """(exec_ms, value) or None if it blew the budget.

    `value` matters as much as the timing: an engine that abandons a backtracking
    search on a step limit has to return SOMETHING, and if that something differs from
    its peers the case is a value discrepancy, not a timing one.
    """
    with open(SPEC_PATH, "w") as f:
        json.dump({"pattern": pattern, "flags": flags, "input": inp}, f)
    try:
        p = subprocess.run(ENGINE_CMD[engine] + [HARNESS, SPEC_PATH],
                           capture_output=True, text=True,
                           timeout=BUDGET_MS / 1000.0 + 4.0)
    except subprocess.TimeoutExpired:
        return None                      # blew the wall clock => over budget
    for line in p.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and "ok" in o:
            if not o["ok"]:
                print(f"    regex error on {engine}: {o['error']}")
                return None
            return float(o["exec_ms"]), o.get("value")
    return None


def measure(engine, pattern, flags, inp, repeats=1):
    """(min-of-repeats exec_ms, value), or None if any run blew the budget."""
    best, val = None, None
    for _ in range(repeats):
        m = measure_once(engine, pattern, flags, inp)
        if m is None:
            return None
        ms, val = m
        best = ms if best is None else min(best, ms)
    return best, val


def largest_true(pred, lo, hi):
    if not pred(lo):
        return None
    if pred(hi):
        return hi
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if pred(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def smallest_true(pred, lo, hi):
    if pred(lo):
        return lo
    if not pred(hi):
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if pred(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def ols(xs, ys):
    """(slope, intercept, R^2) by hand -- no numpy in the image, and this is 6 lines."""
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


def run(case, engine):
    print(f"\n-- {engine}")
    cache = {}

    def t(n):
        if n not in cache:
            cache[n] = measure(engine, case["pattern"], case["flags"], case["make"](n))
        return cache[n]

    def under_budget(n):
        v = t(n)
        return v is not None and v[0] <= BUDGET_MS

    def above_floor(n):
        v = t(n)
        return v is None or v[0] >= FLOOR_MS    # None == over budget == certainly above floor

    lo, hi = case["lo"], case["hi"]
    n_hi = largest_true(under_budget, lo, hi)
    if n_hi is None:
        print(f"   OVER BUDGET even at n={lo} -- no measurable regime in [{lo},{hi}]")
        return
    n_lo = smallest_true(above_floor, lo, hi)
    if n_lo is None:
        ms, val = t(n_hi)
        print(f"   BELOW THE {FLOOR_MS}ms FLOOR across all of [{lo},{hi}] "
              f"(n={n_hi} -> {ms:.4f}ms, value={val})")
        print("   VERDICT: SAFE / unmeasurable -- never crosses the floor at any "
              "reachable length")
        return
    if n_lo > n_hi:
        print(f"   EMPTY BAND: floor first crossed at n={n_lo}, budget already blown by "
              f"n={n_hi}. Growth is too steep to sample between them.")
        return

    print(f"   band: n in [{n_lo}, {n_hi}]  (floor {FLOOR_MS}ms, budget {BUDGET_MS:.0f}ms)")
    step = max(1, (n_hi - n_lo) // (N_POINTS - 1)) if n_hi > n_lo else 1
    ns = sorted({n for n in range(n_lo, n_hi + 1, step)} | {n_hi})
    pts = []
    for n in ns:
        v = measure(engine, case["pattern"], case["flags"], case["make"](n), REPEATS)
        if v is not None and v[0] >= FLOOR_MS:
            pts.append((n, v[0], v[1]))
    print("   points: " + "  ".join(f"({n}, {ms:.2f}ms, {val})" for n, ms, val in pts))
    if len(pts) < 3:
        print(f"   only {len(pts)} usable point(s) -- cannot fit")
        return

    xs = [p[0] for p in pts]
    ys = [math.log(p[1]) for p in pts]
    e = ols(xs, ys)                              # log t ~ n      => exponential
    p = ols([math.log(x) for x in xs], ys)       # log t ~ log n  => polynomial
    if not e or not p:
        print("   fit failed")
        return
    base, k = math.exp(e[0]), p[0]
    print(f"   exponential: base={base:.3f}  R2={e[2]:.4f}")
    print(f"   polynomial:  k={k:.2f}       R2={p[2]:.4f}")

    # Comparing R2 alone does not work: over a narrow band an exponential ALSO fits a
    # power law well (R2 0.993 at k=12.8). So bound the parameter too -- a degree-12
    # polynomial is not a complexity class, it is what an exponential looks like when
    # you force a power law onto it. Backtracking degree is bounded by the quantifier
    # nesting, so k>6 means the power-law model is simply wrong.
    if e[2] >= 0.99 and base >= 1.1 and e[2] > p[2]:
        print(f"   VERDICT: EXPONENTIAL base {base:.2f}  (R2 {e[2]:.4f} vs poly {p[2]:.4f})")
        return
    if p[2] >= 0.99 and k <= 6.0 and p[2] > e[2]:
        print(f"   VERDICT: POLYNOMIAL degree {k:.2f}  (R2 {p[2]:.4f} vs exp {e[2]:.4f})")
        return

    # Neither model fits the whole band. The usual cause is a REGIME CHANGE: an engine
    # with a backtracking step limit is exponential until the limit, then flat. Fitting
    # across that knee gives a meaningless answer, so find the longest prefix that is
    # cleanly exponential and report the tail separately.
    for kk in range(len(pts), 3, -1):
        ek = ols(xs[:kk], ys[:kk])
        if ek and ek[2] >= 0.995 and math.exp(ek[0]) >= 1.1:
            if kk < len(pts):
                flat = pts[kk:]
                print(f"   KNEE at n={pts[kk - 1][0]}: exponential base "
                      f"{math.exp(ek[0]):.2f} (R2 {ek[2]:.4f}) over n="
                      f"{pts[0][0]}..{pts[kk - 1][0]}, then FLAT at "
                      f"~{sum(f[1] for f in flat) / len(flat):.0f}ms through n={flat[-1][0]}")
                print(f"   VERDICT: EXPONENTIAL base {math.exp(ek[0]):.2f} UP TO A CAP "
                      f"-- the engine stops searching, it does not stay fast")
            return
    print(f"   VERDICT: UNCLASSIFIED (exp R2 {e[2]:.4f} base {base:.2f}; "
          f"poly R2 {p[2]:.4f} k {k:.2f}) -- no single model, no clean knee")


only = {int(a) for a in sys.argv[1:]} or set(range(len(CASES)))
for i, case in enumerate(CASES):
    if i not in only:
        continue
    print("\n" + "=" * 78)
    print(f"[{i}] {case['name']}")
    print(f"expect: {case['expect']}")
    for engine in case["engines"]:
        run(case, engine)
print("\n" + "=" * 78)
