"""Dev-only: capture the raw sweep curve for specific rids the way nominate_probe does,
so classify() can be iterated OFFLINE against real corpus curves + the controls.

Writes analysis/redos_nomination/dev_curves.json:
  { rid: {pattern, flags, seed_len, points:[{len,ms,value}], baseline_ms, ok, error},
    "__controls__": { name: {pattern, flags, points, baseline_ms, ...} } }

Run inside the container with the working tree mounted:
  docker run --rm -v "$PWD":/work -w /work verbal:latest \
      bash -lc 'PYTHONPATH=/work/src python3 analysis/redos_nomination/dev_capture.py'
"""
import glob, json, os, re, signal, subprocess, sys

sys.path.insert(0, "/work/src")
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
from pipeline.chaos import mutants, rng_for  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "ladder_harness.js")
SPEC = "/tmp/dev_spec.json"
WINDOW = os.path.join(os.getcwd(), "results-run-6000-9999")

CHAOS_OPS = ("delete", "insert", "substitute", "duplicate", "transpose",
             "case_flip", "truncate")
CHAOS_ALPHABET = tuple("abcXYZ019 _-.!@#/\\\t\n")
CHAOS_N = 2
SEED = 20260716
ORACLE_MS = 200

TARGETS = ["regex_6580", "regex_9577", "regex_7984", "regex_8206", "regex_8848"]

# Same controls nominate_probe uses.
P3910 = r'''(?:\b[a-z\d](?:[_.:+]?[a-z\d]+)*_?_|`[^`]+`_?_|_`[^`]+`)(?=[\s\-.,:;!?\\\/'")\]}]|$)'''
S3910 = "le0i1xoa2bbhey0vg79f2mtujiqktmqt5gqwpa9g49vet63zwun2ancc0z87p_#}]"
CONTROLS = [
    ("regex_3910 raw fuzzer string", P3910, "g", S3910, "EXPONENTIAL"),
    ("/(a+)+$/ non-matching seed", r"(a+)+$", "", "a" * 40 + "!", "EXPONENTIAL"),
    ("/(a+)+$/ MATCHING seed", r"(a+)+$", "", "a" * 40, "SAFE"),
    ("/^a+$/ non-matching seed", r"^a+$", "", "a" * 40 + "!", "SAFE"),
]


class _OT(Exception):
    pass


signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(_OT()))


def matches_bounded(rx, s):
    signal.setitimer(signal.ITIMER_REAL, ORACLE_MS / 1000)
    try:
        return bool(rx.search(s)), False
    except _OT:
        return False, True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def mid_delete(s, L):
    a, b = (L + 1) // 2, L // 2
    return s[:a] + (s[len(s) - b:] if b else "")


def ladder(seed, max_rungs=60):
    n = len(seed)
    if n <= max_rungs:
        Ls = range(1, n + 1)
    else:
        step = n / max_rungs
        Ls = sorted({max(1, int(1 + i * step)) for i in range(max_rungs)} | {n})
    return [mid_delete(seed, L) for L in Ls]


def sweep(pattern, flags, inputs, engine="node"):
    with open(SPEC, "w") as f:
        json.dump({"pattern": pattern, "flags": flags, "inputs": inputs}, f)
    cmd = {"node": ["node"], "bun": ["bun"],
           "deno": ["deno", "run", "--quiet", "--allow-read"]}[engine]
    try:
        p = subprocess.run(cmd + [HARNESS, SPEC], capture_output=True, text=True,
                           timeout=180)
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
    return {"ok": False, "error": (p.stderr or "no output").strip()[:200]}


def derive_seed(rid):
    path = f"{WINDOW}/{rid}/test.strings.jsonl"
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
    pattern, flags = meta["pattern"], meta.get("flags", "")
    rx = re.compile(pattern)
    seen = set(fuzz)
    nonmatching = []
    for i, s in enumerate(fuzz):
        rng = rng_for(SEED, rid, "test", i)
        for m, _ in mutants(s, CHAOS_N, rng, CHAOS_OPS, CHAOS_ALPHABET, seen):
            seen.add(m)
            matched, timed_out = matches_bounded(rx, m)
            if not matched:
                nonmatching.append((m, timed_out))
    if not nonmatching:
        return pattern, flags, None
    seed = max(nonmatching, key=lambda mt: (mt[1], len(mt[0])))[0]
    return pattern, flags, seed


out = {}
for rid in TARGETS:
    pattern, flags, seed = derive_seed(rid)
    print(f"{rid}: /{pattern}/  seed_len={seed and len(seed)}", flush=True)
    if seed is None:
        out[rid] = {"pattern": pattern, "flags": flags, "seed": None}
        continue
    res = sweep(pattern, flags, ladder(seed))
    out[rid] = {"pattern": pattern, "flags": flags, "seed_len": len(seed),
                "seed": seed, **res}

ctl = {}
for name, pat, fl, seed_s, expect in CONTROLS:
    res = sweep(pat, fl, ladder(seed_s))
    ctl[name] = {"pattern": pat, "flags": fl, "expect": expect,
                 "seed_len": len(seed_s), **res}
    print(f"control {name}: ok={res.get('ok')}", flush=True)
out["__controls__"] = ctl

with open(os.path.join(HERE, "dev_curves.json"), "w") as f:
    json.dump(out, f, indent=1)
print("wrote dev_curves.json")
