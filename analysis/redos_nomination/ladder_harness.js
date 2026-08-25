// Time an explicit ladder of inputs, ordered shortest-first, in ONE process, under a
// PER-RUNG wall-clock bound.
//
// The ladder is built in Python (chaos mutant -> middle-deletion rungs) rather than
// here: the construction is the part with a design question in it, so it belongs
// somewhere testable, and the harness stays a stopwatch.
//
// Repeat-loop timing, per micro_harness.js: a test() at the bottom of a ladder costs
// well under a microsecond, which performance.now() cannot resolve one-shot. Looping to
// an accumulation target and dividing reads it to ~0.1%.
//
// Stops at the first rung costing STOP_MS. Ladders are ascending, so everything above
// is more expensive and unnecessary -- the growth rate is already determined by then.
//
// THE PER-RUNG BOUND (the oracle-bound lesson, one level down). STOP_MS only protects
// against rungs we CHOSE to run; it cannot protect against a rung whose single test()
// call never returns, because a real corpus regex can make the ENGINE ITSELF backtrack
// catastrophically -- and re.test() is synchronous and uninterruptible in-thread, so no
// in-thread timer can bound it (the exact shape of the SIGALRM oracle bound and
// 930c43b's generate bound). So the timing runs in a WORKER thread and the main thread
// is a watchdog: if any one rung runs past PER_RUNG_MS with no progress, it terminates
// the worker (worker.terminate() DOES interrupt a running native regex on V8) and
// reports {hung:true}. A tripped bound is not an error -- an engine that hangs on a
// short input is the strongest possible ReDoS signal, so classify() promotes it.
//
// node/bun take the bounded worker path (both expose node:worker_threads + eval
// workers). deno -- not used by the corpus run -- takes the legacy inline path, where a
// hung rung still falls to the caller's outer subprocess timeout as before.

const isDeno = typeof Deno !== "undefined";
const argv = (typeof process !== "undefined" && process.argv) ? process.argv.slice(2) : Deno.args;
const raw = isDeno ? Deno.readTextFileSync(argv[0]) : require("fs").readFileSync(argv[0], "utf8");
const spec = JSON.parse(raw);

// The whole measurement, shared verbatim by the deno inline path AND (via
// Function.toString) the worker. `emit` streams progress so the watchdog can see which
// rung is in flight: {baseline} -> {start,len} -> {point,p} per rung -> {done} (or
// {error} on a bad pattern). A rung that hangs stops after its {start} and never emits
// {point} -- that silence is exactly what the watchdog trips on.
function runSweep(spec, emit) {
  const ACCUM_MS = spec.accum_ms || 2;
  const STOP_MS = spec.stop_ms || 5;
  // Which API is timed. `test` is the default and is what the corpus nominator sweeps,
  // so omitting this leaves every existing caller byte-identical. The others exist
  // because a differential can live in what an API does AFTER the search -- build a
  // result string, split at every match, allocate a match object -- and the confirm
  // artifact's biggest engine gaps on regex_14648 are on replace/split, not test.
  const API = spec.api || "test";
  let sink = 0;
  // Must be defined INSIDE runSweep: the bounded path ships this function to the worker
  // via Function.toString, so anything it closes over from module scope would be
  // undefined there.
  function once(re, s) {
    switch (API) {
      case "replace": return s.replace(re, "").length;
      case "split":   return s.split(re).length;
      case "match":   { const m = s.match(re); return m ? m.length : 0; }
      case "search":  return s.search(re);
      default:        return re.test(s) ? 1 : 0;
    }
  }
  function perCall(re, s) {
    for (let i = 0; i < 5; i++) sink += once(re, s);           // warm the compiled path
    let k = 1;
    for (;;) {
      const t0 = performance.now();
      for (let i = 0; i < k; i++) sink += once(re, s);
      const dt = performance.now() - t0;
      if (dt >= ACCUM_MS) return dt / k;
      if (k > 1e8) return dt / k;
      k *= 4;
    }
  }
  let re;
  try {
    re = new RegExp(spec.pattern, spec.flags);
  } catch (e) {
    emit({ type: "error", error: String(e) });
    return;
  }
  // Cost of a call that searches nothing, in the SAME api -- classify()'s "10x call
  // overhead" cut is only meaningful against the overhead of the call being timed, and
  // s.replace()/s.split() allocate where test() does not.
  const baseline = perCall(new RegExp("a"), "a");
  emit({ type: "baseline", ms: baseline });
  for (const s of spec.inputs) {
    emit({ type: "start", len: s.length });
    const ms = perCall(re, s);
    // `test` keeps emitting a boolean so existing consumers of `value` are unchanged.
    emit({ type: "point", p: { len: s.length, ms,
                               value: API === "test" ? re.test(s) : once(re, s) } });
    if (ms >= STOP_MS) break;
  }
  emit({ type: "done", sink });
}

function runInline(spec) {
  // deno / no-worker fallback: no per-rung bound (a hang here hits the outer timeout).
  let baseline = null;
  const points = [];
  runSweep(spec, (m) => {
    if (m.type === "baseline") baseline = m.ms;
    else if (m.type === "point") points.push(m.p);
    else if (m.type === "done")
      console.log(JSON.stringify({ ok: true, baseline_ms: baseline, points, sink: m.sink }));
    else if (m.type === "error")
      console.log(JSON.stringify({ ok: false, error: m.error }));
  });
}

function runBounded(spec) {
  const { Worker } = require("node:worker_threads");
  const PER_RUNG_MS = spec.per_rung_ms || 1000;
  const workerSrc =
    "const { parentPort, workerData } = require('node:worker_threads');\n" +
    "const runSweep = " + runSweep.toString() + ";\n" +
    "runSweep(workerData, (m) => parentPort.postMessage(m));\n";
  const w = new Worker(workerSrc, { eval: true, workerData: spec });

  const points = [];
  let baseline = null, curLen = null, done = false, timer = null;
  const arm = () => { if (timer) clearTimeout(timer); timer = setTimeout(onHang, PER_RUNG_MS); };
  function finish(obj) {
    if (done) return;
    done = true;
    if (timer) clearTimeout(timer);
    console.log(JSON.stringify(obj));
    w.terminate();
  }
  function onHang() {
    // A rung ran past PER_RUNG_MS with no progress: the engine is backtracking in a
    // single uninterruptible test(). Report the partial curve plus the hung length.
    finish({ ok: true, hung: true, hung_len: curLen, baseline_ms: baseline, points });
  }
  arm();
  w.on("message", (m) => {
    if (done) return;
    if (m.type === "baseline") { baseline = m.ms; arm(); }
    else if (m.type === "start") { curLen = m.len; arm(); }
    else if (m.type === "point") { points.push(m.p); arm(); }
    else if (m.type === "done") finish({ ok: true, baseline_ms: baseline, points, sink: m.sink });
    else if (m.type === "error") finish({ ok: false, error: m.error });
  });
  w.on("error", (e) => finish({ ok: false, error: String(e) }));
  w.on("exit", () => { if (timer) clearTimeout(timer); });
}

if (isDeno) runInline(spec);
else runBounded(spec);
