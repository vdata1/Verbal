// Root-cause probe for F003 (see ../DISCREPANCIES.md#f003): bun does not case-fold
// property escapes under /i. Written while F003 was still just a gap-analysis
// hypothesis (EXPERIMENT_GAPS.md G3b), before the pipeline could generate an input
// that reached it; `chaos` (d1f3125) later surfaced the same bug from the corpus.
//
// Nail down the /\p{Lu}/iu behaviour. Spec (ES2015+, 22.2.2.7.1 CharacterSetMatcher):
// under /u + /i the matcher canonicalizes the input char to cc via simple case
// folding, then matches if THERE EXISTS a member `a` of the CharSet with
// Canonicalize(a) === cc. scf("A") === "a", and "A" is in \p{Lu}, so
// /\p{Lu}/iu.test("a") must be TRUE. Same reasoning: /\p{Ll}/iu.test("A") is TRUE.
//
// This is pure ASCII. No astral code points, no Unicode version skew involved.

const T = [
  // [expr, expected-per-spec, note]
  [() => /\p{Lu}/iu.test("a"), true, '/\\p{Lu}/iu.test("a")   -- scf("a")="a", "A" in Lu folds to "a"'],
  [() => /\p{Ll}/iu.test("A"), true, '/\\p{Ll}/iu.test("A")   -- mirror case'],
  [() => /\p{Lu}/iu.test("A"), true, '/\\p{Lu}/iu.test("A")   -- trivially true'],
  [() => /\p{Lu}/u.test("a"), false, '/\\p{Lu}/u.test("a")    -- CONTROL: no /i, must be false'],
  [() => /\p{Ll}/u.test("A"), false, '/\\p{Ll}/u.test("A")    -- CONTROL: no /i, must be false'],
  [() => /[A-Z]/iu.test("a"), true, '/[A-Z]/iu.test("a")     -- CONTROL: classic range folding'],
  [() => /[a-z]/iu.test("A"), true, '/[a-z]/iu.test("A")     -- CONTROL: classic range folding'],
  [() => /\p{Lu}/vi.test("a"), true, '/\\p{Lu}/vi.test("a")   -- v flag instead of u'],
  [() => /\p{Uppercase_Letter}/iu.test("a"), true, '/\\p{Uppercase_Letter}/iu.test("a") -- long name'],
  [() => /[\p{Lu}]/iu.test("a"), true, '/[\\p{Lu}]/iu.test("a") -- inside a class'],
  [() => /\p{Lu}/iu.test("é"), true, '/\\p{Lu}/iu.test("é")   -- non-ASCII BMP (É is Lu)'],
];

const name = typeof Deno !== "undefined" ? "deno"
           : typeof Bun !== "undefined" ? "bun"
           : "node";
console.log(`===== ${name} =====`);
let fails = 0;
for (const [fn, expected, note] of T) {
  let got;
  try { got = fn(); } catch (e) { got = `THREW ${e.name}`; }
  const ok = got === expected;
  if (!ok) fails++;
  console.log(`  ${ok ? "pass" : "FAIL"}  ${note}`);
  if (!ok) console.log(`          expected ${expected}, got ${got}`);
}
console.log(`  --> ${T.length - fails}/${T.length} match the spec`);
