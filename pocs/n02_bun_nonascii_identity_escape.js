// N-02 -- bun/JSC: a non-ASCII IdentityEscape is ACCEPTED under u/v. ES2024 22.2.1
// IdentityEscape[UnicodeMode] permits only SyntaxCharacter or "/", so \C-cedilla must
// be a SyntaxError in unicode mode.
// WRONG ENGINE: bun   |   PARSER, not JIT. bun is over-permissive here, so code that
// compiles on bun fails to load at all on node and deno.
// Recorded on: node v26.5.0 (V8 14.6.202) | bun 1.3.14 (JavaScriptCore) | deno 2.9.1 (V8 14.9.207)
// Run under all three:  node F  /  bun F  /  deno run --quiet F
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;
const P = (label, value) => console.log(`  ${E.padEnd(12)} ${label} -> ${value}`);
const SHOW = (s) => s === null || s === undefined ? String(s)
  : `"${[...s].map(c => c.codePointAt(0) > 126 || c.codePointAt(0) < 32
      ? "\\u{" + c.codePointAt(0).toString(16).toUpperCase() + "}" : c).join("")}"`;

const tryPat = (p, f) => { try { const r = new RegExp(p, f); return "ok, test=" + r.test("Ç"); } catch (e) { return e.name; } };

P('new RegExp("\\\\Ç", "u")   (want SyntaxError)', tryPat("\\Ç", "u"));
P('new RegExp("\\\\Ç", "v")   (want SyntaxError)', tryPat("\\Ç", "v"));

// CONTROL 1: without u/v, an identity escape of any character is legal (Annex B) --
// all three engines accept it and match.
P('CONTROL no flags              (want ok, test=true)', tryPat("\\Ç", ""));

// CONTROL 2: an ASCII letter escape IS correctly rejected by bun under u, so bun
// does enforce the rule -- just not for non-ASCII.
P('CONTROL "\\\\a" under /u        (want SyntaxError)', tryPat("\\a", "u"));

// CONTROL 3: "/" is an explicitly permitted IdentityEscape -- accepted everywhere.
P('CONTROL "\\\\/" under /u        (want ok)', tryPat("\\/", "u"));
