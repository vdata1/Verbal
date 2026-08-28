// N-03 -- bun/JSC: an unescaped TRAILING `-` in a v-mode character class is accepted
// where it must be a SyntaxError. ES2024 22.2.1 lists `-` as a ClassSetSyntaxCharacter,
// so inside a `v` class it must be escaped unless it forms a ClassSetRange. In `[a-]`
// the `-` is trailing, so it cannot form a range, and the pattern must not compile.
// WRONG ENGINE: bun   |   PARSER, not JIT.
//
// REQUIRES bun 1.3.11 -- this one is FIXED in the pinned 1.3.14, so on the artifact's
// pinned engines every line below reads "ok". Reproduce it with:
//   curl -fsSL -o bun.zip https://github.com/oven-sh/bun/releases/download/bun-v1.3.11/bun-<platform>.zip
//   unzip -q bun.zip && ./bun-<platform>/bun n03_bun_vmode_trailing_dash_accepted.js
//
// Recorded on: bun 1.3.11 (reproduces) | bun 1.3.14, node v26.5.0, deno 2.9.1 (all correct)
// Run under all three:  node F  /  bun F  /  deno run --quiet F
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;
const P = (label, value) => console.log(`  ${E.padEnd(12)} ${label} -> ${value}`);

const tryPat = (p, f) => {
  try { new RegExp(p, f); return "ok (compiles)"; } catch (e) { return e.name; }
};

// A trailing `-` after a completed operand. All must be SyntaxError; bun 1.3.11
// compiles every one of them.
P('/[a-]/v      (want SyntaxError)', tryPat("[a-]", "v"));
P('/[ab-]/v     (want SyntaxError)', tryPat("[ab-]", "v"));
P('/[\\w-]/v     (want SyntaxError)', tryPat("[\\w-]", "v"));
P('/[a-]/vi     (want SyntaxError)', tryPat("[a-]", "vi"));

// CONTROL 1: a LEADING `-`, and a lone `-`. bun 1.3.11 rejects these correctly, so
// the gap is specifically the trailing position, not `-` handling in general.
P('CONTROL /[-a]/v (want SyntaxError)', tryPat("[-a]", "v"));
P('CONTROL /[-]/v  (want SyntaxError)', tryPat("[-]", "v"));

// CONTROL 2: a `-` after a COMPLETED range. Also rejected by 1.3.11, which narrows
// the trigger further: it is a `-` directly following a single ClassSetOperand.
P('CONTROL /[a-c-]/v (want SyntaxError)', tryPat("[a-c-]", "v"));

// CONTROL 3: the correct spelling, and the same class outside v mode. These compile
// everywhere -- `u` mode and legacy mode both admit a trailing `-` as a literal, so
// the divergence is confined to `v`.
P('CONTROL /[a\\-]/v escaped (want ok)', tryPat("[a\\-]", "v"));
P('CONTROL /[a-]/u          (want ok)', tryPat("[a-]", "u"));
P('CONTROL /[a-]/  no flags (want ok)', tryPat("[a-]", ""));

// Say plainly which side of the fix this build is on, so a run on the pinned engines
// is not mistaken for a broken reproducer.
const buggy = tryPat("[a-]", "v") === "ok (compiles)";
console.log(
  buggy
    ? `\n  ${E}: REPRODUCES -- /[a-]/v compiled and must not have.`
    : `\n  ${E}: fix present -- /[a-]/v correctly rejected. Use bun 1.3.11 to see the bug.`
);
