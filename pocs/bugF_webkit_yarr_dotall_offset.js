// Bug F -- WebKit/Yarr JIT: with lastIndex > 0, the `s` flag changes where the match
// STARTS -- the engine returns a match beginning BEFORE the search start it was given.
// WRONG ENGINE: JSC   |   Yarr JIT miscompile: 24/57 wrong with the JIT, 0/57 under
// --useRegExpJIT=0, and on that set the interpreter agrees with both V8 targets.
//
// NOT bun-specific: Apple's shipped system jsc reproduces it case-for-case with no bun
// in the picture, so the defect is in upstream Yarr and is live in Safari too:
//   /System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc \
//     -e 'const re=/.*X.*/gs; re.lastIndex=1; const m=re.exec("aaXb"); print(`@${m.index} "${m[0]}"`)'
// Recorded on: node v26.5.0 (V8 14.6.202) | bun 1.3.14 (JavaScriptCore) | deno 2.9.1 (V8 14.9.207)
// Run under all three:  node F  /  bun F  /  deno run --quiet F
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;
const P = (label, value) => console.log(`  ${E.padEnd(12)} ${label} -> ${value}`);
const SHOW = (s) => s === null || s === undefined ? String(s)
  : `"${[...s].map(c => c.codePointAt(0) > 126 || c.codePointAt(0) < 32
      ? "\\u{" + c.codePointAt(0).toString(16).toUpperCase() + "}" : c).join("")}"`;

// "aaXb" contains NO line terminator, so `s` -- which only controls whether `.`
// matches line terminators -- cannot legally change anything here.
const gs = /.*X.*/gs; gs.lastIndex = 1;
const a = gs.exec("aaXb");
P('/.*X.*/gs  @lastIndex 1  (want "aXb" @1)', a ? `${SHOW(a[0])} @${a.index}` : "null");

// CONTROL: drop the s and JSC is correct, in every tier and engine.
const g = /.*X.*/g; g.lastIndex = 1;
const b = g.exec("aaXb");
P('CONTROL /.*X.*/g @lastIndex 1  (want "aXb" @1)', b ? `${SHOW(b[0])} @${b.index}` : "null");

// THE KILLER LINE FOR A MAINTAINER: [\s\S] already matches every code point, so `s`
// is a no-op BY CONSTRUCTION -- not merely for this subject. Same pattern, same
// subject, same semantics; only the flag differs, and the answer changes. There is
// no reading of the spec under which these two calls may differ.
const k1 = new RegExp("[\\s\\S]*X[\\s\\S]*", "g");  k1.lastIndex = 1;
const k2 = new RegExp("[\\s\\S]*X[\\s\\S]*", "gs"); k2.lastIndex = 1;
P('[\\s\\S]*X[\\s\\S]* /g   (want @1)', k1.exec("aaXb").index);
P('[\\s\\S]*X[\\s\\S]* /gs  (want @1)', k2.exec("aaXb").index);

// WHY BUN'S OWN DIVERGENCE CORPUS MISSED IT: the bug needs lastIndex MANUALLY
// preseeded > 0 before the first exec. Natural iteration from 0 returns "aaXb"@0 on
// node, deno and buggy bun alike -- no divergence, because at offset 0 the match
// legitimately starts at 0.
P('CONTROL natural matchAll from 0 (all agree)',
  Array.from("aaXb".matchAll(/.*X.*/gs)).map(x => SHOW(x[0]) + "@" + x.index).join(", "));
