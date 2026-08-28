// V8: the regexp INTERPRETER abandons backtracking at an internal budget and returns
// `null` where V8's own regexp COMPILER returns the correct match -- same pattern, same
// subject, on two consecutive calls of the same RegExp object.
// WRONG ENGINE: V8, so BOTH node and deno. This is not a bun finding.
//
// THE PATTERN IS NULLABLE, so no oracle and no majority vote is needed. `((a*)*b)*` is
// a star over a group; zero iterations is a legal parse, so it matches "" at index 0 of
// EVERY subject and exec() may never return null. This file proves that on the accused
// engine itself, in the same process, at the end.
//
// WHY THE DEFAULT CONFIGURATION SERVES THE WRONG TIER FIRST
//   V8 ships --regexp-tier-up-ticks=1: the FIRST execution of a pattern runs in the
//   irregexp interpreter, and only later ones use compiled code. So a cold process -- a
//   CLI run, a serverless handler, the first request after a deploy -- gets the
//   interpreter, which is the tier that returns the wrong answer. Nothing in the API
//   surfaces which tier ran, and nothing distinguishes this `null` from a real no-match.
//
// The interpreter's wrong answer arrives at a FLAT cost that no longer depends on the
// input, while the compiler keeps paying the exponential and stays correct -- the same
// signature as bun's step cap in f004. Note the compiler is both correct AND 5x faster
// here, so this is a limit one tier has, not a disagreement about the pattern.
//
//   node, one cold process each                        result   time
//   n=31  default (first exec is interpreted)          null     143.0 s
//   n=31  --regexp-interpret-all                       null     144.3 s
//   n=31  --no-regexp-tier-up  (compiler)              ""        27.8 s
//   n=30  --regexp-interpret-all                       ""       106.1 s
//
// n=30 is the last length the interpreter gets right. Doubling from its 106.1 s there
// predicts ~212 s at n=31; it gives up at 144.3 s instead. A search that finished would
// have taken longer, not less -- which is what a budget being hit looks like.
//
// SLOW BY NATURE -- a couple of minutes. The interpreter has to do the exponential work
// honestly to reach its budget; that is the point and it cannot be shortcut.
//
// Run (each is one cold process):
//   node                                               F
//   node --regexp-interpret-all                        F
//   node --no-regexp-tier-up                           F
//   deno run --quiet --v8-flags=--regexp-interpret-all F
//
// UNDER bun THIS ALSO RETURNS null, FOR A DIFFERENT REASON: bun/JSC has its own step cap
// whose crossover on this driver is n=26, and it answers in ~1.6 s rather than ~143 s.
// That is f004. Do not read bun's null here as the V8 finding.
//
// Recorded on: node v26.5.0 (V8 14.6.202) | deno 2.9.1 (V8 14.9.207) | bun 1.3.14
"use strict";
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;

const SRC = "((a*)*b)*";
const N = 31;

// THE TIMED CALL MUST COME FIRST. V8's regexp code cache is keyed on the pattern SOURCE
// and the tier-up tick counter rides along, so any earlier execution of this same source
// -- including the nullability proof below -- tiers the pattern up, and this call then
// runs COMPILED and answers correctly. Putting the proof first hides the divergence.
const t = Date.now();
const m = new RegExp(SRC).exec("a".repeat(N));
const ms = Date.now() - t;
console.log(`  ${E.padEnd(12)} /${SRC}/.exec("a".repeat(${N}))  (want "") -> ` +
            `${m === null ? "null" : JSON.stringify(m[0])}   ${ms} ms`);

// The nullability proof, now that the timed call is done: a fresh RegExp on the empty
// subject. The accused engine exhibits the empty match itself.
console.log(`  ${E.padEnd(12)} exec("") on the same pattern     (want "") -> ` +
            `${JSON.stringify(new RegExp(SRC).exec("")[0])}`);

console.log(
  m === null
    ? `\n  ${E}: returned null for a pattern that matches "" at index 0 of every\n` +
      `  subject. On node/deno, re-run with --no-regexp-tier-up (or make a second call\n` +
      `  in the same process) to get the compiler tier and the correct answer.`
    : `\n  ${E}: correct -- this run used the compiler tier.`
);
