"""Can a regex be classified as ReDoS-prone from TINY inputs only -- a1, aa1, aaa1?

The proposal: never test a big string at all. Sweep n=1..~15, fit, and flag. A long
input is then only ever run to CONFIRM something already nominated -- and only for the
few that get nominated.

This automates regex_3910_size_analysis.js in this directory, where the same question
was answered by hand: that file records 5s/11s/22s at n=26/27/28 -- ~38s of measurement
to see a doubling. The sweep here classifies the same regex from a 24-char input in
milliseconds, and extrapolates back onto those three figures to within 5-17%.

The obstacle is the noise floor, not the string size. The cold-exec sweep in
../../differential_findings/bun_backtrack_cap__unsound_step_limit/sweep_probe.py could
not see below ~1ms, which put node's band at n=13..23. That is already small -- 23
chars -- but it is not n=1..5. micro_harness.js loops instead, dropping the floor to
~1us, which is what this checks: does the exponential slope survive all the way down to
single-digit n?

Every point here costs microseconds. The whole per-regex sweep never runs an input
costing more than 5ms.
"""
import json, math, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "micro_harness.js")
SPEC = "/tmp/micro_spec.json"
ENGINE_CMD = {"node": ["node"], "bun": ["bun"],
              "deno": ["deno", "run", "--quiet", "--allow-read"]}

P3910 = r'''(?:\b[a-z\d](?:[_.:+]?[a-z\d]+)*_?_|`[^`]+`_?_|_`[^`]+`)(?=[\s\-.,:;!?\\\/'")\]}]|$)'''

CASES = [
    dict(name="/(a+)+$/  'a'*n+'!'        [the proposal: a!, aa!, aaa!, ...]",
         pattern=r"(a+)+$", flags="", pump="a", suffix="!", expect="EXPONENTIAL base 2"),
    dict(name="/(a+)+$/  'a'*n            [MATCHES -- control]",
         pattern=r"(a+)+$", flags="", pump="a", suffix="", expect="safe"),
    dict(name="/^a+$/    'a'*n+'!'        [negative control]",
         pattern=r"^a+$", flags="", pump="a", suffix="!", expect="safe/linear"),
    dict(name="/a+b/     'a'*n            [polynomial]",
         pattern=r"a+b", flags="", pump="a", suffix="", expect="POLYNOMIAL k~2", n_max=400),
    dict(name="regex_3910 'l'+'e'*n+'_#}]' [real corpus row]",
         pattern=P3910, flags="g", prefix="l", pump="e", suffix="_#}]",
         expect="EXPONENTIAL base 2"),
    dict(name="/(a|aa)+$/ 'a'*n+'!'       [different ambiguity shape]",
         pattern=r"(a|aa)+$", flags="", pump="a", suffix="!", expect="EXPONENTIAL"),
]


def sweep(engine, case):
    spec = {k: case[k] for k in ("pattern", "flags", "prefix", "pump", "suffix", "n_max")
            if k in case}
    with open(SPEC, "w") as f:
        json.dump(spec, f)
    p = subprocess.run(ENGINE_CMD[engine] + [HARNESS, SPEC],
                       capture_output=True, text=True, timeout=120)
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
    print(f"    no output from {engine}: {p.stderr.strip()[:200]}")
    return None


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


for case in CASES:
    print("\n" + "=" * 78)
    print(f"{case['name']}\nexpect: {case['expect']}")
    for engine in ("node", "bun", "deno"):
        r = sweep(engine, case)
        if r is None or not r["ok"]:
            print(f"-- {engine}: {r and r.get('error')}")
            continue
        base, pts = r["baseline_ms"], r["points"]
        print(f"-- {engine}   (call overhead {base * 1000:.3f}us)")
        shown = [f"({p['n']},{p['ms'] * 1000:.2f}us)" for p in pts[:16]]
        print("   " + " ".join(shown) + (" ..." if len(pts) > 16 else ""))
        print(f"   swept n=1..{pts[-1]['n']}, longest input {pts[-1]['len']} chars, "
              f"dearest call {pts[-1]['ms']:.3f}ms, value={pts[-1]['value']}")

        # Only fit where the signal clears the call overhead by 10x -- below that the
        # curve is measuring the cost of calling test(), not the cost of searching.
        usable = [p for p in pts if p["ms"] >= 10 * base]
        if len(usable) < 3:
            print(f"   SAFE / no growth: never reached 10x the call overhead "
                  f"({len(usable)} usable point(s))")
            continue
        xs = [p["n"] for p in usable]
        ys = [math.log(p["ms"]) for p in usable]
        e = ols(xs, ys)
        p_ = ols([math.log(x) for x in xs], ys)
        if not e or not p_:
            print("   fit failed")
            continue
        b, k = math.exp(e[0]), p_[0]
        print(f"   fit on n={xs[0]}..{xs[-1]} ({len(xs)} pts): "
              f"exp base={b:.3f} R2={e[2]:.4f} | poly k={k:.2f} R2={p_[2]:.4f}")
        if e[2] >= 0.99 and b >= 1.1 and e[2] > p_[2]:
            print(f"   >>> NOMINATE: EXPONENTIAL base {b:.2f}")
        elif p_[2] >= 0.99 and k <= 6 and p_[2] > e[2]:
            print(f"   >>> POLYNOMIAL degree {k:.2f}"
                  + ("  (NOMINATE: superlinear)" if k >= 1.5 else "  (linear -- safe)"))
        else:
            print(f"   >>> unclassified (exp R2 {e[2]:.4f} b={b:.2f}; "
                  f"poly R2 {p_[2]:.4f} k={k:.2f})")
print("\n" + "=" * 78)
