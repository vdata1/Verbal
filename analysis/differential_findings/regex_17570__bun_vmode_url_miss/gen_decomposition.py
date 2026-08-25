"""Round 2: decompose the corpus pattern into its components and find the minimal
sub-pattern that still shows bun's `v`-flag blowup.

Round 1 over-reduced: P1 dropped the second domain-label group AND the TLD group, and ran
in 0.0ms. The cost lives somewhere between the full pattern and that. Here we remove one
component at a time and also test the domain branch in full.

Oracle for THIS round is within-engine: same bun, same pattern, same input, `v` vs no flag.
The `v` flag is semantically inert for these sub-patterns (no set operations, no string
literals), so any ratio above ~1 is bun-specific cost. A within-engine ratio needs no
second engine and is immune to how loaded the box is.
"""
import json, re

HARNESS = "/scratch/turcotte/verbal/results/regex_17570/test__18__v.js"
src = open(HARNESS).read()
def grab(n):
    return json.loads(re.search(rf'^const {n} = (".*");$', src, re.M).group(1))
FULL_PAT, FULL_IN = grab("pattern"), grab("input")

A  = r"(?:(?:http|https|ftp)://)"
B  = r"(?:\S+(?::\S*)?@)?"
C1 = r"(?:[1-9]\d?|1\d\d|2[01]\d|22[0-3])(?:\.(?:1?\d{1,2}|2[0-4]\d|25[0-5])){2}(?:\.(?:[0-9]\d?|1\d\d|2[0-4]\d|25[0-4]))"
LBL  = r"(?:(?:[a-z¡-￿0-9]+-?)*[a-z¡-￿0-9]+)"
LBLS = r"(?:\.(?:[a-z¡-￿0-9]+-?)*[a-z¡-￿0-9]+)*"
TLD  = r"(?:\.(?:[a-z¡-￿]{2,}))"
C2 = LBL + LBLS + TLD
C  = f"(?:(?:{C1}|{C2})|localhost)"
D  = r"(?::\d{2,5})?"
E  = r"(?:(/|\?|#)[^\s]*)?"

CAND = [
    ("FULL (recomposed)",        f"^{A}{B}{C}{D}{E}$"),
    ("minus A (scheme)",         f"^{B}{C}{D}{E}$"),
    ("minus B (userinfo)",       f"^{A}{C}{D}{E}$"),
    ("minus D (port)",           f"^{A}{B}{C}{E}$"),
    ("minus E (path)",           f"^{A}{B}{C}{D}$"),
    ("minus C1 (ipv4 branch)",   f"^{A}{B}(?:(?:{C2})|localhost){D}{E}$"),
    ("minus localhost",          f"^{A}{B}(?:{C1}|{C2}){D}{E}$"),
    ("C2 domain branch alone",   f"^{C2}$"),
    ("  C2 minus TLD",           f"^{LBL}{LBLS}$"),
    ("  C2 minus LBLS",          f"^{LBL}{TLD}$"),
    ("  LBL alone",              f"^{LBL}$"),
    ("  LBLS alone",             f"^{LBLS}$"),
    ("  TLD alone",              f"^{TLD}$"),
    ("  LBL + TLD, no anchors",  f"{LBL}{TLD}"),
]
def esc(p):
    """Render non-ASCII as \\uXXXX, the form the corpus harness uses."""
    return "".join(c if ord(c) < 128 else "\\u%04x" % ord(c) for c in p)

CAND = [(n, esc(p)) for n, p in CAND]

# sanity: the recomposition must be byte-identical to the corpus pattern
recomposed = esc(f"^{A}{B}{C}{D}{E}$")
print("recomposition matches corpus pattern:", recomposed == FULL_PAT)
if recomposed != FULL_PAT:
    print("  corpus:", FULL_PAT[:120]); print("  ours  :", recomposed[:120])

INPUTS = [("I0 corpus input", FULL_IN)]

js = r'''"use strict";
const PATTERNS = %s;
const INPUTS = %s;
const out = [];
for (const [pname, p] of PATTERNS) {
  for (const [iname, s] of INPUTS) {
    const row = {pattern: pname, input: iname};
    for (const flags of ["v", ""]) {
      let value = null, err = null, ms = null;
      try {
        const re = new RegExp(p, flags);
        const t0 = performance.now();
        value = re.test(s);
        ms = performance.now() - t0;
      } catch (e) { err = e.constructor.name + ": " + e.message; }
      row[flags || "none"] = {value, err, ms: ms === null ? null : Math.round(ms*1000)/1000};
    }
    out.push(row);
  }
}
console.log(JSON.stringify({engine: ENGINE, rows: out}));
''' % (json.dumps(CAND, ensure_ascii=True), json.dumps(INPUTS, ensure_ascii=True))

base = "/tmp/claude-2004/-home-turcotte-projects-verbal/c2cb0bf3-7741-4cbb-8598-464c7d8cc71a/scratchpad"
for eng in ("node", "bun", "deno"):
    open(f"{base}/decomp_{eng}.js", "w").write(f'const ENGINE = {json.dumps(eng)};\n' + js)
print("wrote decomp_{node,bun,deno}.js —", len(CAND), "patterns")
