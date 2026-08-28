// F004 -- bun/JSC: backtracking is abandoned at an internal step budget and the engine
// returns a genuine-looking "no match". A cap meant to prevent ReDoS becomes a silent
// validator bypass: make the input long enough and the match disappears.
// WRONG ENGINE: bun
//
// Two drivers, because they fail differently and the second needs no outside oracle.
//
//   PART 1  /(a+)+$/ over "a"*n + "!aaa"  -- unanchored, so the trailing "aaa" matches
//           for every n. bun flips true -> false at exactly n=26.
//   PART 2  /(\s*(\/\*(.*?\s*?)*\*\/)*)*/ over an UNCLOSED comment -- NULLABLE, so it
//           matches "" at index 0 of every subject and exec() may never return null.
//           bun returns null from n=18. The same bun process returns "" for exec("")
//           a line later, so nothing outside bun is needed to see the contradiction.
//
// The budget is in STEPS, not milliseconds: a heavier inner loop plateaus at ~1780 ms
// instead of ~680 ms. The crossover n reproduces across hosts; the wall-clock does not.
// Cite the crossover, never the milliseconds. Past the cap the answer stops depending
// on the input at all -- bun stays wrong out to n=100+ at a flat cost.
//
// A RangeError would be defensible. A false/null is not: bun does not SIGNAL
// exhaustion, it returns a value indistinguishable from a real no-match.
//
// SLOW BY NATURE: ~3 s. node and deno do the exponential work honestly, which is why
// each part stops where V8 is still quick -- past that a head-to-head takes minutes.
//
// Recorded on: node v26.5.0 (V8 14.6.202) | bun 1.3.14 (JavaScriptCore) | deno 2.9.1 (V8 14.9.207)
// Run under all three:  node F  /  bun F  /  deno run --quiet F
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;
const P = (label, value) => console.log(`  ${E.padEnd(12)} ${label} -> ${value}`);
const show = (m) => m === null ? "null" : JSON.stringify(m[0]);

// --- PART 1: the unanchored driver -------------------------------------------------
// Correct answer is true at every n. Read the per-n timings with care: within one
// process V8 tiers the regexp up to compiled code partway through, so n=24 pays that
// warmup and n=25 can come out faster. One n per fresh process gives the honest curve.
for (const n of [24, 25, 26]) {
  const t0 = Date.now();
  const got = /(a+)+$/.test("a".repeat(n) + "!aaa");
  P(`/(a+)+$/  n=${String(n).padStart(3)}  (want true)`, `${got}   ${Date.now() - t0}ms`);
}

// --- PART 2: the nullable driver ---------------------------------------------------
const SRC = "(\\s*(/\\*(.*?\\s*?)*\\*/)*)*";
const build = (n) => "/*" + " ".repeat(n);

// The reference ladder, kept where V8 is quick. All three engines return the empty
// match, which is the correct answer at every length.
for (const n of [12, 13, 14]) {
  const t0 = Date.now();
  const got = show(new RegExp(SRC).exec(build(n)));
  P(`nullable  n=${String(n).padStart(3)}  (want "")`, `${got}   ${Date.now() - t0}ms`);
}

// The flip. bun returns null for the same pattern that just matched "". node and deno
// are correct here too; they simply take minutes to say so, so they are skipped.
for (const n of [17, 18]) {
  if (E.startsWith("bun")) {
    const t0 = Date.now();
    const got = show(new RegExp(SRC).exec(build(n)));
    P(`nullable  n=${String(n).padStart(3)}  (want "")`, `${got}   ${Date.now() - t0}ms`);
  } else {
    P(`nullable  n=${String(n).padStart(3)}  (want "")`, "skipped -- V8 needs minutes here");
  }
}

// CONTROL: close the comment and the ambiguity collapses -- one parse, no search, and
// every engine answers instantly at any length. The cap is reached by the exhaustive
// exploration, not by the input being long.
{
  const t0 = Date.now();
  const got = show(new RegExp(SRC).exec("/*" + " ".repeat(40) + "*/"));
  P("CONTROL   closed comment n=40 (want a match)", `${got.slice(0, 20)}   ${Date.now() - t0}ms`);
}

// The nullability proof, last: a fresh RegExp on the empty subject. The accused engine
// exhibits the empty match itself, in this same process.
//
// ORDER MATTERS. This must stay after the timed calls. V8's regexp code cache is keyed
// on the pattern source with the tier-up tick counter riding along, so running this
// first would tier the pattern up and change which tier the calls above use.
P('CONTROL   exec("") on the same pattern (want "")', show(new RegExp(SRC).exec("")));
