// Bug A -- bun/JSC: a v-mode character class matches only the HIGH SURROGATE of an
// astral code point, returning a string that is not well-formed UTF-16.
// WRONG ENGINE: bun   |   Yarr JIT miscompile: 17/59 wrong with the JIT, 0/59 under
// BUN_JSC_useRegExpJIT=0. Ground truth needs no cross-engine vote -- the same binary
// disagrees with itself across execution tiers.
// Recorded on: node v26.5.0 (V8 14.6.202) | bun 1.3.14 (JavaScriptCore) | deno 2.9.1 (V8 14.9.207)
// Run under all three:  node F  /  bun F  /  deno run --quiet F
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;
const P = (label, value) => console.log(`  ${E.padEnd(12)} ${label} -> ${value}`);
const SHOW = (s) => s === null || s === undefined ? String(s)
  : `"${[...s].map(c => c.codePointAt(0) > 126 || c.codePointAt(0) < 32
      ? "\\u{" + c.codePointAt(0).toString(16).toUpperCase() + "}" : c).join("")}"`;

// U+D801 is General_Category=Cs. It is NOT in \p{L}. So this is not a truncated
// match of a set member -- bun returns a code unit the class does not contain.
const a = new RegExp("[\\s\\t\\p{L}]", "v").exec("\u{10400}");
P('[\\s\\t\\p{L}]/v on U+10400  (want U+10400, length 2)',
  `${SHOW(a && a[0])}  length ${a ? a[0].length : "-"}`);

// Same shape with other property operands.
const b = new RegExp("[\\d0\\p{N}]", "v").exec("\u{1D7CE}");
P('[\\d0\\p{N}]/v on U+1D7CE     (want U+1D7CE, length 2)',
  `${SHOW(b && b[0])}  length ${b ? b[0].length : "-"}`);

// CONTROL 1: the same class under u instead of v -- correct in every engine. v-only.
const c = new RegExp("[\\s\\t\\p{L}]", "u").exec("\u{10400}");
P('CONTROL same class under /u    (want U+10400, length 2)',
  `${SHOW(c && c[0])}  length ${c ? c[0].length : "-"}`);

// CONTROL 2: a range operand instead of a property escape -- correct under v too.
const d = new RegExp("[\\s\\t\\u{1F600}-\\u{1F610}]", "v").exec("\u{1F601}");
P('CONTROL range operand under /v (want U+1F601, length 2)',
  `${SHOW(d && d[0])}  length ${d ? d[0].length : "-"}`);
