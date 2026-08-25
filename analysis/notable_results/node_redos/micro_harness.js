// Whole length-sweep for ONE regex, inside ONE process, from tiny inputs only.
//
// Two differences from sweep_harness.js, both deliberate:
//
//  1. REPEAT-LOOP timing, not one cold exec. A single test() at n=5 is ~4 microseconds;
//     performance.now() cannot see that. Looping until >=ACCUM_MS of work accumulates
//     and dividing gives a per-call figure good to ~0.1%, which drops the noise floor
//     from ~1ms to ~1us and puts n=3..15 in range. The cost is that this measures WARM
//     (JIT-compiled) steady state rather than the cold path run_eval sees -- which for
//     classifying GROWTH is an improvement: removing a constant startup overhead makes
//     the small-n end fit better, not worse.
//
//  2. It sweeps n itself and stops at STOP_MS. One process per (regex, engine) instead
//     of one per (regex, engine, n) -- ~30ms of engine startup amortised over the whole
//     curve, which is what makes this affordable over a whole corpus.
//
// The sweep never runs an input costing more than STOP_MS. It cannot hang.
const argv = (typeof process !== "undefined" && process.argv) ? process.argv.slice(2) : Deno.args;
const raw = (typeof Deno !== "undefined")
  ? Deno.readTextFileSync(argv[0]) : require("fs").readFileSync(argv[0], "utf8");
const spec = JSON.parse(raw);

const ACCUM_MS = 5;      // per-point accumulation target => ~0.1% timer error
const STOP_MS = 5;       // stop growing n once ONE call costs this much
const N_MAX = spec.n_max || 40;

let sink = 0;            // accumulated so no JIT can eliminate the calls

function perCall(re, s) {
  for (let i = 0; i < 5; i++) sink += re.test(s) ? 1 : 0;   // warm up the compiled path
  let k = 1;
  for (;;) {
    const t0 = performance.now();
    for (let i = 0; i < k; i++) sink += re.test(s) ? 1 : 0;
    const dt = performance.now() - t0;
    if (dt >= ACCUM_MS) return dt / k;
    if (k > 1e8) return dt / k;
    k *= 4;
  }
}

try {
  const re = new RegExp(spec.pattern, spec.flags);
  // Cost of a test() call that does no searching: the floor everything else sits on.
  const baseline = perCall(new RegExp("a"), "a");
  const points = [];
  for (let n = 1; n <= N_MAX; n++) {
    const s = (spec.prefix || "") + (spec.pump || "a").repeat(n) + (spec.suffix || "");
    const ms = perCall(re, s);
    points.push({n, ms, len: s.length, value: re.test(s)});
    if (ms >= STOP_MS) break;
  }
  console.log(JSON.stringify({ok: true, baseline_ms: baseline, points, sink}));
} catch (e) {
  console.log(JSON.stringify({ok: false, error: String(e)}));
}
