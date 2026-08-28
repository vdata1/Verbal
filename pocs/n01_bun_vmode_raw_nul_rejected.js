// N-01 -- bun/JSC: a RAW NUL inside a v-mode character class is rejected with a
// SyntaxError. ES2024 22.2.1 ClassSetSyntaxCharacter does not list U+0000, so it is
// a permitted ClassSetCharacter and the pattern must compile.
// WRONG ENGINE: bun   |   PARSER, not JIT.
// Recorded on: node v26.5.0 (V8 14.6.202) | bun 1.3.14 (JavaScriptCore) | deno 2.9.1 (V8 14.9.207)
// Run under all three:  node F  /  bun F  /  deno run --quiet F
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;
const P = (label, value) => console.log(`  ${E.padEnd(12)} ${label} -> ${value}`);
const SHOW = (s) => s === null || s === undefined ? String(s)
  : `"${[...s].map(c => c.codePointAt(0) > 126 || c.codePointAt(0) < 32
      ? "\\u{" + c.codePointAt(0).toString(16).toUpperCase() + "}" : c).join("")}"`;

const NUL = String.fromCharCode(0);
const tryPat = (p, f) => { try { new RegExp(p, f); return "ok (compiles)"; } catch (e) { return e.name; } };

P('new RegExp("[" + NUL + "]", "v")   (want ok)', tryPat("[" + NUL + "]", "v"));

// The corpus row this came from -- a raw C0 range, 480 discrepant cells in one window.
P('raw [U+0000-U+001F U+007F] /v      (want ok)',
  tryPat("[" + NUL + "-" + String.fromCharCode(0x1f) + String.fromCharCode(0x7f) + "]", "v"));

// CONTROL 1: the same raw NUL under u, and with no flags -- accepted everywhere.
P('CONTROL same class under /u        (want ok)', tryPat("[" + NUL + "]", "u"));
P('CONTROL same class, no flags       (want ok)', tryPat("[" + NUL + "]", ""));

// CONTROL 2: the ESCAPED form is accepted by bun under v, so it is specifically the
// raw code unit the v-mode parser rejects.
P('CONTROL escaped [\\0] under /v      (want ok)', tryPat("[\\0]", "v"));
