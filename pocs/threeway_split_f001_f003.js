// THREE-WAY SPLIT -- F001 (deno) and F003 (bun) compose: one matchAll call in which
// node, bun and deno each return something DIFFERENT, each engine wrong about a
// different character for an unrelated reason.
//
// This is the case against any majority-vote oracle. Note also that eight of the ten
// findings split as node+deno vs bun -- which is V8 agreeing with ITSELF, not two
// independent engines concurring.
// Recorded on: node v26.5.0 (V8 14.6.202) | bun 1.3.14 (JavaScriptCore) | deno 2.9.1 (V8 14.9.207)
// Run under all three:  node F  /  bun F  /  deno run --quiet F
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;
const P = (label, value) => console.log(`  ${E.padEnd(12)} ${label} -> ${value}`);
const SHOW = (s) => s === null || s === undefined ? String(s)
  : `"${[...s].map(c => c.codePointAt(0) > 126 || c.codePointAt(0) < 32
      ? "\\u{" + c.codePointAt(0).toString(16).toUpperCase() + "}" : c).join("")}"`;

// "a" needs bun's missing /i fold (F003); U+16EAC needs deno's Unicode 17.0 tables (F001).
const subject = "a\u{16EAC}\n\u{1CBA}\n\u{420}\n";
const got = Array.from(subject.matchAll(new RegExp("\\p{Uppercase_Letter}", "giu"))).map(m => m[0]);

P("matchAll(/\\p{Uppercase_Letter}/giu)", `${got.length} matches: ${got.map(SHOW).join(", ")}`);

console.log(`
  Expected across the three engines:
    node   4 matches: "a", U+16EAC, U+1CBA, U+420    correct on both axes
    bun    3 matches:      U+16EAC, U+1CBA, U+420    drops "a"       <- F003
    deno   3 matches: "a",          U+1CBA, U+420    drops U+16EAC   <- F001

  Neither finding alone predicts this: it needs bun's folding bug AND deno's table
  lag in the same string. On another input the same pair produces bun,deno | node --
  a 2-vs-1 partition in which the MAJORITY is wrong.`);
