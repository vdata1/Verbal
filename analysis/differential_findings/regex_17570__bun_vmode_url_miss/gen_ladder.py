"""Build the reduction ladder for regex_17570 v-mode, from the ORIGINAL harness.

Pattern and input are lifted verbatim out of the recorded harness so nothing is lost to
transcription. The ladder walks from the 300-char corpus pattern down to a single
character class, and from the 60-char fuzz input down to one code unit, testing each
under `v` and under no flag so the v-only claim is checked at every rung.
"""
import json, re, os

HARNESS = "/scratch/turcotte/verbal/results/regex_17570/test__18__v.js"
src = open(HARNESS).read()

def grab(name):
    m = re.search(rf'^const {name} = (".*");$', src, re.M)
    return json.loads(m.group(1))

FULL_PAT = grab("pattern")
FULL_IN = grab("input")

# Where the surrogates are in the corpus input -- the reduction hypothesis
lone = [(i, hex(ord(c))) for i, c in enumerate(FULL_IN) if 0xD800 <= ord(c) <= 0xDFFF]
print("lone/paired surrogates in the corpus input:", lone)

CLS = "[a-z\\u00a1-\\uffff0-9]"           # the class the domain branch is built from
HI  = "[\\u00a1-\\uffff]"                  # just its high range (covers D800-DFFF)

PATTERNS = [
    ("P0 full corpus pattern",            FULL_PAT),
    ("P1 domain branch only",             f"^(?:(?:{CLS}+-?)*{CLS}+)$"),
    ("P2 P1 minus the -? ",               f"^(?:{CLS}+)*{CLS}+$"),
    ("P3 P1, class = high range only",    f"^(?:{HI}+-?)*{HI}+$"),
    ("P4 nested quantifier, no anchor2",  f"^(?:{HI}+)*$"),
    ("P5 single quantified class",        f"^{HI}+$"),
    ("P6 ONE class, ONE char",            HI),
    ("P7 explicit surrogate range",       "[\\ud800-\\udfff]"),
    ("P8 class w/ a second operand",      f"[a-z\\u00a1-\\uffff]"),
]

LONE = "\ud865"          # a lone HIGH surrogate taken from the corpus input
PAIR = "𩕁"    # the same high surrogate, properly paired
BMP  = "烢"          # the char that follows it in the corpus input

INPUTS = [
    ("I0 full corpus input",  FULL_IN),
    ("I1 lone high surrogate", LONE),
    ("I2 lone + next BMP",     LONE + BMP),
    ("I3 well-formed pair",    PAIR),
    ("I4 BMP only",            BMP),
]

js = r'''"use strict";
// regex_17570 v-mode reduction ladder.
// Oracle is a VALUE divergence (bun false / V8 true), which is load-invariant --
// safe to run on a busy box. Times are reported but are not the oracle.
const PATTERNS = %s;
const INPUTS = %s;
const out = [];
for (const [pname, p] of PATTERNS) {
  for (const [iname, s] of INPUTS) {
    for (const flags of ["v", ""]) {
      let value = null, err = null, ms = null;
      try {
        const re = new RegExp(p, flags);
        const t0 = performance.now();
        value = re.test(s);
        ms = performance.now() - t0;
      } catch (e) { err = e.constructor.name + ": " + e.message; }
      out.push({pattern: pname, input: iname, flags, value, err,
                ms: ms === null ? null : Math.round(ms * 1000) / 1000});
    }
  }
}
console.log(JSON.stringify({engine: ENGINE, rows: out}));
''' % (json.dumps(PATTERNS, ensure_ascii=True), json.dumps(INPUTS, ensure_ascii=True))

os.makedirs("/tmp/claude-2004/-home-turcotte-projects-verbal/c2cb0bf3-7741-4cbb-8598-464c7d8cc71a/scratchpad", exist_ok=True)
base = "/tmp/claude-2004/-home-turcotte-projects-verbal/c2cb0bf3-7741-4cbb-8598-464c7d8cc71a/scratchpad"
for eng in ("node", "bun", "deno"):
    with open(f"{base}/ladder_{eng}.js", "w") as fh:
        fh.write(f'const ENGINE = {json.dumps(eng)};\n' + js)
print("wrote ladder_{node,bun,deno}.js")
print("patterns:", len(PATTERNS), "inputs:", len(INPUTS),
      "cases per engine:", len(PATTERNS) * len(INPUTS) * 2)
