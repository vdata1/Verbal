// F003 -- bun/JSC: \p{...} property escapes are not case-folded under /i.
// WRONG ENGINE: bun   |   ES2024 22.2.2.7.1 CharacterSetMatcher requires the fold.
// Recorded on: node v26.5.0 (V8 14.6.202) | bun 1.3.14 (JavaScriptCore) | deno 2.9.1 (V8 14.9.207)
// Run under all three:  node F  /  bun F  /  deno run --quiet F
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;
const P = (label, value) => console.log(`  ${E.padEnd(12)} ${label} -> ${value}`);

// U+10EA GEORGIAN LETTER CAN folds to itself; its Mtavruli capital U+1CAA is
// General_Category=Lu, hence in \p{Uppercase_Letter}. Under /i the set must match it.
P('/\\p{Uppercase_Letter}/iu.test("\u{10EA}") (want true)',
  new RegExp("\\p{Uppercase_Letter}", "iu").test("\u{10EA}"));

// The same defect on plain ASCII, both directions, and inside a class.
P('/\\p{Lu}/iu.test("a")              (want true)', new RegExp("\\p{Lu}", "iu").test("a"));
P('/\\p{Ll}/iu.test("A")              (want true)', new RegExp("\\p{Ll}", "iu").test("A"));
P('/[\\p{Lu}]/iu.test("a")            (want true)', new RegExp("[\\p{Lu}]", "iu").test("a"));
P('/\\p{Lu}/vi.test("a")              (want true)', new RegExp("\\p{Lu}", "vi").test("a"));

// THE ARGUMENT: bun contradicts itself. It folds a literal range correctly and a
// property escape not at all -- so it is not applying a different-but-coherent
// theory of /i, it applies the fold in one place and omits it in the other.
P('/[A-Z]/iu.test("a")   RANGE FOLD  (want true)', /[A-Z]/iu.test("a"));
P('/[a-z]/iu.test("A")   RANGE FOLD  (want true)', /[a-z]/iu.test("A"));

// CONTROLS without /i -- all three engines agree, so the property SET is right
// in bun; only the folding step is missing.
P('CONTROL /\\p{Lu}/u.test("a")       (want false)', new RegExp("\\p{Lu}", "u").test("a"));
P('CONTROL /\\p{Lu}/u.test("A")       (want true)',  new RegExp("\\p{Lu}", "u").test("A"));
