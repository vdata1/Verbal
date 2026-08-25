// Hypothesis: JSC (bun) treats a `^` inside a ZERO-MATCHABLE group as if it
// anchored the whole pattern, so it refuses matches at index > 0 when `m` is absent.
// V8 (node, deno) correctly allows the group to match zero times anywhere.
const cases = [
  // [label, pattern, flags, input, what a correct engine must find]
  ["minimal: ^ in lazy *? group",      "(?:^x)*?y",   "g", "ay",        "y at 1"],
  ["minimal: ^ in optional ? group",   "(?:^x)?y",    "g", "ay",        "y at 1"],
  ["minimal: ^ in greedy * group",     "(?:^x)*y",    "g", "ay",        "y at 1"],
  ["control: bare ^ (really anchored)", "^y",         "g", "ay",        "(no match - correct)"],
  ["control: ^ with m flag",           "(?:^x)*?y",   "gm", "ay",       "y at 1"],
  ["srt-shaped: ^.*$\\n in lazy group", "a\\n((?:^.*$\\n)*?)\\n", "g", "zz\na\n\n", "match at 2"],
];
const out = [];
for (const [label, pattern, flags, input, expect] of cases) {
  let got;
  try {
    const ms = Array.from(input.matchAll(new RegExp(pattern, flags)));
    got = ms.length ? ms.map(m => `${JSON.stringify(m[0])}@${m.index}`).join(",") : "NO MATCH";
  } catch (e) { got = "THREW " + e.name; }
  out.push({label, pattern, flags, expect, got});
}
console.log(JSON.stringify(out, null, 1));
