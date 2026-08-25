"""Is bun's backtracking cap SOUND?

sweep_probe.py established that bun is exponential (base 2.03) on /(a+)+$/ until
n~25, then flat at ~676ms however long the input gets. That is a step limit: bun stops
searching. It returned `false` there -- correct, because that input genuinely does not
match, so an engine that gives up and an engine that searches exhaustively agree.

This asks the question that separates them. Input: "a"*n + "!aaa".

  /(a+)+$/ is NOT anchored at the start, so it matches the trailing "aaa" -- the answer
  is TRUE for every n. But a backtracking engine reaches that match only AFTER failing
  at start positions 0..n-1, each of which costs a full exponential partition search of
  the leading a-run.

So the match lies on the far side of the exponential wall. An engine that abandons the
search at a step limit and reports "no match" is WRONG here, and wrong in a way no
timing measurement would show: it answers fast, and it answers false.

Ground truth is analytic (the trailing "aaa" matches $), and confirmed at small n where
every engine still completes.
"""
import json, os, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "sweep_harness.js")
SPEC = "/tmp/cap_spec.json"
ENGINE_CMD = {"node": ["node"], "bun": ["bun"],
              "deno": ["deno", "run", "--quiet", "--allow-read"]}
WALL_S = 25.0

PATTERN, FLAGS = r"(a+)+$", ""


def run(engine, inp):
    with open(SPEC, "w") as f:
        json.dump({"pattern": PATTERN, "flags": FLAGS, "input": inp}, f)
    try:
        p = subprocess.run(ENGINE_CMD[engine] + [HARNESS, SPEC],
                           capture_output=True, text=True, timeout=WALL_S)
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
    return None


print(f"regex /{PATTERN}/{FLAGS}  vs  'a'*n + '!aaa'")
print("correct answer is TRUE for every n (the trailing 'aaa' matches $)\n")
print(f"{'n':>4} | {'node':>22} | {'bun':>22} | {'deno':>22}")
print("-" * 78)

wrong = []
for n in [5, 10, 15, 20, 22, 24, 26, 28, 30, 34, 40, 60, 100]:
    inp = "a" * n + "!aaa"
    cells = []
    for e in ("node", "bun", "deno"):
        r = run(e, inp)
        if r is None:
            cells.append(f"{'TIMEOUT >25s':>22}")
        else:
            ms, val = r
            flag = "" if val is True else "  <<< WRONG"
            cells.append(f"{ms:10.2f}ms {str(val):>5}{flag:>6}")
            if val is not True:
                wrong.append((e, n, ms, val))
    print(f"{n:>4} | " + " | ".join(cells))

print()
if wrong:
    print("!!! UNSOUND CAP -- an engine reported a WRONG value, fast:")
    for e, n, ms, val in wrong:
        print(f"      {e} n={n}: returned {val} in {ms:.1f}ms; correct answer is True")
    print("\n    This is a VALUE discrepancy, not a timing one. An engine that abandons")
    print("    a backtracking search and reports 'no match' is not slow -- it is wrong,")
    print("    and it is wrong in the one direction a timing oracle cannot see.")
else:
    print("Every engine that answered, answered True. The cap is sound on this input;")
    print("bun simply refuses to spend more than ~680ms and still gets it right.")
