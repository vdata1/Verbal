// F001 -- deno: regexp \p{...} tables are Unicode 16.0-era while deno self-reports 17.0.
// WRONG ENGINE: deno   (node and bun are correct)
// Recorded on: node v26.5.0 (V8 14.6.202) | bun 1.3.14 (JavaScriptCore) | deno 2.9.1 (V8 14.9.207)
// Run under all three:  node F  /  bun F  /  deno run --quiet F
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;
const P = (label, value) => console.log(`  ${E.padEnd(12)} ${label} -> ${value}`);

// U+32D50 is CJK Ext J, assigned in Unicode 17.0. It is a letter.
P("[\\p{L}0-9]/u on U+32D50   (want true)",
  new RegExp("[\\p{L}0-9]", "u").test(String.fromCodePoint(0x32D50)));

// The lag is table-wide, not \p{L}-only.
P("\\p{Script=Han}/u on U+323B0 (want true)",
  new RegExp("\\p{Script=Han}", "u").test(String.fromCodePoint(0x323B0)));

// CONTROL 1: a 16.0 addition (U+105C0 Todhri) -- all three engines say true.
P("CONTROL 16.0 letter U+105C0    (want true)",
  new RegExp("\\p{L}", "u").test(String.fromCodePoint(0x105C0)));

// CONTROL 2: unassigned in 17.0, just past the end of Ext J -- all three say false,
// so deno carries real 16.0 data rather than approximating whole planes.
P("CONTROL unassigned U+33480    (want false)",
  new RegExp("\\p{L}", "u").test(String.fromCodePoint(0x33480)));

// The self-report is what makes this a clear bug: deno claims the same Unicode/ICU
// version as node while its regexp tables behave a full major version behind.
if (typeof process !== "undefined" && process.versions && process.versions.unicode)
  P("self-reported unicode/icu", process.versions.unicode + " / " + process.versions.icu);
