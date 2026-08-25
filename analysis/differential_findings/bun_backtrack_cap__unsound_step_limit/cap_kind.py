"""Is bun's backtracking cap a STEP limit or a TIME limit?

This decides whether F004 is reproducible. bun plateaus at ~676ms on /(a+)+$/ however
long the input gets, and abandons the search there (see bun_cap_probe.py). Two readings:

  STEP limit -- bun stops after N backtracks. Wall-clock at the plateau is then
    N * (per-step cost), so a regex with a costlier inner loop plateaus HIGHER. The
    crossover n is then a property of the regex and the engine, and reproduces on any
    host.
  TIME limit -- bun stops after T milliseconds. Every regex plateaus at the same T,
    and the crossover n moves with host speed: a faster machine gets further through
    the search before the clock runs out, so it flips to the wrong answer at a LARGER
    n. That would make the finding host-dependent and unreproducible from provenance --
    exactly the class of problem tracked as G6.

The test: run a regex with a very different per-step cost and compare plateaus.
regex_3910 is a real corpus row with a far heavier inner loop than /(a+)+$/.
"""
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "sweep_harness.js")
SPEC = "/tmp/cap_kind_spec.json"
ENGINE_CMD = {"node": ["node"], "bun": ["bun"],
              "deno": ["deno", "run", "--quiet", "--allow-read"]}

# analysis/notable_results/node_redos/regex_3910_size_analysis.js
P3910 = r'''(?:\b[a-z\d](?:[_.:+]?[a-z\d]+)*_?_|`[^`]+`_?_|_`[^`]+`)(?=[\s\-.,:;!?\\\/'")\]}]|$)'''


def run(engine, pattern, flags, inp, wall_s=30.0):
    with open(SPEC, "w") as f:
        json.dump({"pattern": pattern, "flags": flags, "input": inp}, f)
    try:
        p = subprocess.run(ENGINE_CMD[engine] + [HARNESS, SPEC],
                           capture_output=True, text=True, timeout=wall_s)
    except subprocess.TimeoutExpired:
        return None
    for line in p.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and o.get("ok"):
            return o["exec_ms"], o["value"]
    print(f"    no canonical line from {engine} -- stderr: {p.stderr.strip()[:200]}")
    return None


print("bun plateau on /(a+)+$/ vs 'a'*n+'!'   (the ~676ms cap)")
for n in (24, 26, 28, 32, 40):
    r = run("bun", r"(a+)+$", "", "a" * n + "!")
    print(f"  n={n:>2}: " + ("no reading" if r is None else f"{r[0]:8.1f}ms  value={r[1]}"))

print("\nbun plateau on regex_3910 -- 'l'+'e'*n+'_#}]'   (a much costlier inner loop)")
for n in range(24, 46, 2):
    r = run("bun", P3910, "g", "l" + "e" * n + "_#}]")
    print(f"  n={n:>2}: " + ("no reading" if r is None else f"{r[0]:8.1f}ms  value={r[1]}"))

print("\nDifferent plateaus => the budget is in STEPS, not milliseconds => the crossover")
print("n and the wrong value are host-independent and reproducible from provenance;")
print("only the plateau's wall-clock is a property of this host.")
