// F002 -- bun/JSC: a `^` inside a zero-matchable group anchors the WHOLE pattern.
// WRONG ENGINE: bun   |   Yarr JIT miscompile: BUN_JSC_useRegExpJIT=0 fixes every case.
// Recorded on: node v26.5.0 (V8 14.6.202) | bun 1.3.14 (JavaScriptCore) | deno 2.9.1 (V8 14.9.207)
// Run under all three:  node F  /  bun F  /  deno run --quiet F
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;
const P = (label, value) => console.log(`  ${E.padEnd(12)} ${label} -> ${value}`);

// The group matches zero times, so `^` need never hold and "y" at index 1 must match.
P('matchAll(/(?:^x)*?y/g) on "ay"   (want ["y"])',
  JSON.stringify(Array.from("ay".matchAll(/(?:^x)*?y/g)).map(m => m[0])));

// Not global-specific, and not about laziness -- a bare (?:^)*? does it too.
P('/(?:^)*?y/.exec("ay")             (want "y")',
  JSON.stringify((/(?:^)*?y/.exec("ay") || [null])[0]));

// Corpus witness: needs only a non-zero lastIndex, no m-flag split.
const re = /(^[ \t]+)?(?=\/\/)/g; re.lastIndex = 1;
P('/(^[ \\t]+)?(?=\\/\\/)/g @lastIndex 1 (want true)', re.test("\t\t //x"));

// CONTROL 1: a genuine `^` anchor -- correctly no-match everywhere.
P('CONTROL /^y/g.test("ay")          (want false)', /^y/g.test("ay"));

// CONTROL 2: the symmetric `$` bug does not exist -- correct in all three engines.
P('CONTROL /y(?:x$)*?/g on "ya"      (want "y")',
  JSON.stringify(("ya".match(/y(?:x$)*?/g) || [null])[0]));

// CONTROL 3: the m flag makes it vanish, which is the tell.
P('CONTROL /(?:^x)*?y/gm on "ay"      (want ["y"])',
  JSON.stringify(Array.from("ay".matchAll(/(?:^x)*?y/gm)).map(m => m[0])));
