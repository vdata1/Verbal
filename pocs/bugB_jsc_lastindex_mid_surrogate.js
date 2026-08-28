// Bug B -- JSC: when lastIndex points at a TRAIL surrogate under u/v, bun skips
// forward past the whole code point where V8 backs up to its start.
// WRONG ENGINE: bun   |   NOT a JIT bug (identical under BUN_JSC_useRegExpJIT=0).
//
// SCOPE: this is an interop divergence in an area the specification leaves open, not
// a clean conformance violation. A literal reading of RegExpBuiltinExec yields a THIRD
// answer (a lone low surrogate) that neither V8 nor JSC returns. The case rests on the
// consequences below -- test() goes false, matchAll drops a match, sticky returns null.
// Recorded on: node v26.5.0 (V8 14.6.202) | bun 1.3.14 (JavaScriptCore) | deno 2.9.1 (V8 14.9.207)
// Run under all three:  node F  /  bun F  /  deno run --quiet F
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;
const P = (label, value) => console.log(`  ${E.padEnd(12)} ${label} -> ${value}`);
const SHOW = (s) => s === null || s === undefined ? String(s)
  : `"${[...s].map(c => c.codePointAt(0) > 126 || c.codePointAt(0) < 32
      ? "\\u{" + c.codePointAt(0).toString(16).toUpperCase() + "}" : c).join("")}"`;

// Code units of "\u{10437}2": [0]=D801 [1]=DC37 [2]="2". lastIndex 1 is mid-pair.
const re = /./gu; re.lastIndex = 1;
const m = re.exec("\u{10437}2");
P('/./gu @lastIndex 1   (V8: U+10437 @0)', m ? `${SHOW(m[0])} @${m.index}` : "null");

// The consequences, on subject "a\u{10437}b" with lastIndex = 2 -- three ordinary
// surfaces silently produce wrong answers.
const s = "a\u{10437}b";

// Worst of the three: a boolean surface, so a caller cannot tell this from a real no-match.
const t = new RegExp("\u{10437}", "gu"); t.lastIndex = 2;
P('test() @lastIndex 2              (want true)', t.test(s));

// matchAll is the realistic entry point: it seeds its clone from the source
// regexp's lastIndex, so the common lastIndex footgun carries a mid-pair index in.
const g = new RegExp("[^;]", "gv"); g.lastIndex = 2;
P('matchAll-style /[^;]/gv          (want 2 matches)',
  Array.from(s.matchAll(g)).map(x => SHOW(x[0]) + "@" + x.index).join(", ") || "(none)");

const y = new RegExp("[^;]", "yu"); y.lastIndex = 2;
const ym = y.exec(s);
P('sticky /[^;]/yu @lastIndex 2     (want U+10437 @1)', ym ? `${SHOW(ym[0])} @${ym.index}` : "null");

// CONTROL 1: non-unicode g is unaffected -- this is purely the unicode index adjustment.
const p = /./g; p.lastIndex = 1;
const pm = p.exec("\u{10437}2");
P('CONTROL /./g @lastIndex 1        (all agree)', pm ? `${SHOW(pm[0])} @${pm.index}` : "null");

// CONTROL 2: the ADVANCE path is fine -- AdvanceStringIndex strides by code points
// correctly in bun. Only the initial lastIndex -> match-start mapping is wrong.
const q = /2/gu; q.lastIndex = 0;
const qm = q.exec("\u{10437}2");
P('CONTROL /2/gu from 0             (all agree)', qm ? `${SHOW(qm[0])} @${qm.index}` : "null");
