// F005 -- bun/JSC: a sticky (y) regex with a leading `.*` that must backtrack
// returns null, though a match begins exactly at lastIndex.
// WRONG ENGINE: bun   |   NOT a JIT bug -- identical under BUN_JSC_useRegExpJIT=0.
// Recorded on: node v26.5.0 (V8 14.6.202) | bun 1.3.14 (JavaScriptCore) | deno 2.9.1 (V8 14.9.207)
// Run under all three:  node F  /  bun F  /  deno run --quiet F
const E = typeof Deno !== "undefined" ? "deno " + Deno.version.deno
        : typeof Bun  !== "undefined" ? "bun "  + Bun.version
        : "node " + process.versions.node;
const P = (label, value) => console.log(`  ${E.padEnd(12)} ${label} -> ${value}`);

// Sticky requires only that the match BEGIN at lastIndex (= 0 here). The greedy
// .* eats "zzx", then must give characters back so `x` can match.
P('/.*x.*/y.exec("zzx")            (want "zzx")',
  JSON.stringify((new RegExp(".*x.*", "y").exec("zzx") || [null])[0]));

// CONTROL 1: no overshoot to back off from -- bun is correct here.
P('CONTROL /.*x.*/y.exec("x")      (want "x")',
  JSON.stringify((new RegExp(".*x.*", "y").exec("x") || [null])[0]));

// CONTROL 2: without y, bun finds the very same match.
P('CONTROL /.*x.*/.exec("zzx")     (want "zzx")',
  JSON.stringify((new RegExp(".*x.*", "").exec("zzx") || [null])[0]));

// CONTROL 3: a genuine no-match -- all three engines correctly return null.
P('CONTROL /.+x/y.exec("x")        (want null)',
  JSON.stringify(new RegExp(".+x", "y").exec("x")));

// HOW IT REACHES CALLERS WHO NEVER WRITE `y`: split with a limit that is not
// ALREADY a number. ToUint32("2") is 2, so these two calls must agree.
P('"zzx".split(/.*x.*/, 2)         (want ["",""])', JSON.stringify("zzx".split(/.*x.*/, 2)));
P('"zzx".split(/.*x.*/, "2")       (want ["",""])', JSON.stringify("zzx".split(/.*x.*/, "2")));
P('"zzx".split(/.*x.*/, {valueOf:()=>2}) (want ["",""])',
  JSON.stringify("zzx".split(/.*x.*/, { valueOf: () => 2 })));

// CONTROL 4: lazy -- no backtrack at position 0, so bun is correct.
P('CONTROL "zzx".split(/.*?x/, "2") (all agree)',
  JSON.stringify("zzx".split(/.*?x/, "2")));
