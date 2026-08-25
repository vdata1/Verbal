// Self-contained PoC: JSC (bun) misses matches at index > 0 when `^` appears
// inside a group that can match zero times and the `m` flag is absent.
//
// Run on any JS engine, no dependencies:
//   node poc.js     -> ALL PASS   (V8)
//   deno run poc.js -> ALL PASS   (V8)
//   bun poc.js      -> 4 FAIL     (JavaScriptCore)
//
// Confirmed on node v26.5.0, deno 2.9.1, bun 1.3.14.

// [label, pattern, flags, input, expected "match@index" list per spec]
const cases = [
  ["^ in lazy *? group",            /(?:^x)*?y/g,            "ay",       ['"y"@1']],
  ["^ in optional ? group",         /(?:^x)?y/g,             "ay",       ['"y"@1']],
  ["^ in greedy * group",           /(?:^x)*y/g,             "ay",       ['"y"@1']],
  ["srt-shaped: ^.*$\\n in group",  /a\n((?:^.*$\n)*?)\n/g,  "zz\na\n\n", ['"a\\n\\n"@3']],
  // Controls: these must pass everywhere, and do. They rule out "bun is just
  // broken on ^" and pin the trigger to the zero-matchable-group + no-`m` combo.
  ["control: bare ^ is anchored",   /^y/g,                   "ay",       []],
  ["control: same pattern, m flag", /(?:^x)*?y/gm,           "ay",       ['"y"@1']],
];

let failed = 0;
for (const [label, re, input, expected] of cases) {
  const got = Array.from(input.matchAll(re)).map(m => `${JSON.stringify(m[0])}@${m.index}`);
  const ok = JSON.stringify(got) === JSON.stringify(expected);
  if (!ok) failed++;
  const show = a => (a.length ? a.join(",") : "NO MATCH");
  console.log(
    `${ok ? "pass" : "FAIL"}  ${label.padEnd(30)}  ${String(re).padEnd(24)}` +
    (ok ? `  ${show(got)}` : `  expected ${show(expected)}, got ${show(got)}`)
  );
}

console.log(
  failed === 0
    ? "\nAll 6 cases pass — this engine is spec-correct."
    : `\n${failed}/6 cases FAIL — this engine hoists \`^\` out of a zero-matchable group.`
);
