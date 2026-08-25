// One COLD in-harness measurement of a single api call, for the length-sweep probe.
//
// Mirrors the pipeline harness's measurement discipline deliberately: performance.now()
// wraps the api call ONLY, so engine startup (node 30ms / bun 14ms / deno 20ms --
// engine-correlated, and fatal to a differential timing oracle) and `new RegExp`
// compilation are both excluded. One exec per process, so every reading is cold, the
// same way run_eval sees it; repeats are separate processes, not a warm in-process loop.
//
// Spec arrives as a JSON file path: argv blows ARG_MAX past ~100KB of input, and the
// safe-case controls need strings that long to clear the noise floor at all.
const argv = (typeof process !== "undefined" && process.argv)
  ? process.argv.slice(2)
  : Deno.args;

const raw = (typeof Deno !== "undefined")
  ? Deno.readTextFileSync(argv[0])
  : require("fs").readFileSync(argv[0], "utf8");
const spec = JSON.parse(raw);

try {
  const re = new RegExp(spec.pattern, spec.flags);
  const s = spec.input;
  const t0 = performance.now();
  const v = re.test(s);
  const t1 = performance.now();
  console.log(JSON.stringify({ok: true, exec_ms: t1 - t0, value: v, len: s.length}));
} catch (e) {
  console.log(JSON.stringify({ok: false, error: String(e)}));
}
