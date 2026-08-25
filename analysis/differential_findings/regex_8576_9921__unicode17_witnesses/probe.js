// F001 root-cause probe — runs on node, bun and deno (no deps, any engine).
//
// Three questions, three tables:
//
//   1. ERA LADDER      Is the deno miss-set a clean Unicode-version cutoff?
//                      One representative letter per Unicode era. A correct
//                      engine answers L=Y to every row.
//   2. UNASSIGNED      Is an engine that answers L=Y merely over-matching whole
//                      planes rather than carrying real data? A correct engine
//                      answers L=n to every row.
//   3. CASE MAPPING    Within ONE runtime, do the ICU case-mapping data and the
//                      regexp property tables agree? They are versioned
//                      independently and can skew apart.
//
// Usage:  node probe.js | bun probe.js | deno run --quiet probe.js

const ERAS = [
  [0x0041, "U+0041   A               Unicode 1.0"],
  [0x275D9, "U+275D9  CJK Ext B       Unicode 3.1"],
  [0x1E900, "U+1E900  Adlam           Unicode 9.0"],
  [0x3038E, "U+3038E  CJK Ext G       Unicode 13.0"],
  [0x31350, "U+31350  CJK Ext H       Unicode 15.1"],
  [0x2EBF0, "U+2EBF0  CJK Ext I       Unicode 15.1"],
  [0x105C0, "U+105C0  Todhri          Unicode 16.0"],
  [0x16D40, "U+16D40  Kirat Rai       Unicode 16.0"],
  [0x323B0, "U+323B0  CJK Ext J       Unicode 17.0"],
  [0x16EAC, "U+16EAC  Beria Erfe      Unicode 17.0"],
  [0x18DEF, "U+18DEF  Tangut-area     post-16.0 (node has it, deno does not)"],
];

// Unassigned in Unicode 17.0, chosen to sit just past the end of each block the
// era ladder probes, so an engine that range-matches a whole block is caught.
const UNASSIGNED = [
  [0x33480, "just past CJK Ext J end (U+3347F)"],
  [0x16EE0, "just past Beria Erfe end (U+16EDF)"],
  [0x18E00, "just past U+18DFF"],
  [0x3FFFD, "plane 3, unassigned"],
  [0x40000, "plane 4, unassigned"],
  [0x50000, "plane 5, unassigned"],
];

const name = typeof Deno !== "undefined" ? "deno"
           : typeof Bun !== "undefined" ? "bun"
           : "node";

let reported = "n/a";
try {
  const p = typeof process !== "undefined" ? process : null;
  if (p) reported = `unicode=${p.versions.unicode ?? "?"} icu=${p.versions.icu ?? "?"}`;
} catch (e) { /* ignore */ }

console.log(`===== ${name} =====`);
console.log(`self-reported: ${reported}`);

console.log("\n[1] ERA LADDER — correct answer is L=Y for every row");
for (const [cp, label] of ERAS) {
  const hit = /\p{L}/u.test(String.fromCodePoint(cp));
  console.log(`    L=${hit ? "Y" : "n <-- MISS"}  ${label}`);
}

console.log("\n[2] UNASSIGNED — correct answer is L=n for every row");
for (const [cp, why] of UNASSIGNED) {
  const hit = /\p{L}/u.test(String.fromCodePoint(cp));
  console.log(`    U+${cp.toString(16).toUpperCase()}  L=${hit ? "Y <-- OVER-MATCH" : "n"}  ${why}`);
}

// Beria Erfe (Unicode 17.0) is bicameral, so 17.0 case data maps U+16EAC to a
// lowercase form. toLowerCase() reads ICU case data; \p{Lu} reads the regexp
// property tables. Disagreement WITHIN a runtime means the two data sets skew.
console.log("\n[3] CASE MAPPING vs REGEXP TABLES — same runtime, two data sets");
const UP = 0x16EAC;
const ch = String.fromCodePoint(UP);
const lowerCp = ch.toLowerCase().codePointAt(0);
console.log(`    U+16EAC.toLowerCase() -> U+${lowerCp.toString(16).toUpperCase()}` +
            `   ${lowerCp !== UP ? "[ICU case data: 17.0 present]" : "[ICU case data: pre-17.0]"}`);
console.log(`    /\\p{Lu}/u             -> ${/\p{Lu}/u.test(ch)}` +
            `   [regexp tables: ${/\p{Lu}/u.test(ch) ? "17.0 present" : "pre-17.0"}]`);

// Not just \p{L}: the whole property table lags together.
console.log(`    /\\p{Script=Han}/u on U+323B0 -> ${/\p{Script=Han}/u.test(String.fromCodePoint(0x323B0))}`);
