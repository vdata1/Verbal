// provenance:
//   git_commit: 2684e9ba13da7ec8bfdc787a2dac8fa33854a0c1
//   config_sha: b0e31920351c56cfbeaf3ad889e5df602083232372af52fed8b81a9b9682caf4
//   seed: 0
//   corpus: data/uniq-regexes-8.json
//   corpus_sha: 999fe71e83f0db26931d6810164bff9efefdf3f6791d3444aa770ccdafe280e9
//   chunk_start: 17525
//   chunk_count: 100
//   stage: harness
//   api: test
//   regex_id: regex_17570
//   flags: v
"use strict";
const pattern = "^(?:(?:http|https|ftp)://)(?:\\S+(?::\\S*)?@)?(?:(?:(?:[1-9]\\d?|1\\d\\d|2[01]\\d|22[0-3])(?:\\.(?:1?\\d{1,2}|2[0-4]\\d|25[0-5])){2}(?:\\.(?:[0-9]\\d?|1\\d\\d|2[0-4]\\d|25[0-4]))|(?:(?:[a-z\\u00a1-\\uffff0-9]+-?)*[a-z\\u00a1-\\uffff0-9]+)(?:\\.(?:[a-z\\u00a1-\\uffff0-9]+-?)*[a-z\\u00a1-\\uffff0-9]+)*(?:\\.(?:[a-z\\u00a1-\\uffff]{2,})))|localhost)(?::\\d{2,5})?(?:(/|\\?|#)[^\\s]*)?$";
const flags = "v";
const input = "https://\ub000\ud865\u70e2\ufe70\uc197\uf03f\u8aeb\u0c75\udb1f\ucaf3\u4f89\u1491\uc11c\uc25e\u0679\u5e9c-\uedf1\u4414\u514d\u10bb\u6fcf\u06be\uf010\ue320-\u6034\ubf42\u573f\ue8fc\udd72\uff71\u6b72\u40ea\udd00\u194f\uff63\u3b72\ubf52\ub90a\u8ca1\ud48d\u902b\u15d8\udfd1\u0983\uce2f\ufb29\uddfc\u88b1\u987b\u2d1b-\u4577.\uc90b\ub1c2\u0ee2-\ue435.\u0da7\u62c1";
const api = "test";
const regex_id = "regex_17570";

function enc(x) {
  if (x === undefined) return {"__undef__": true};
  if (Array.isArray(x)) return x.map(enc);
  return x;
}
function serializeMatch(m) {
  if (m === null) return null;
  const out = {match: m[0], groups: Array.prototype.slice.call(m, 1).map(enc), index: m.index};
  if (m.groups) {
    const named = {};
    for (const k of Object.keys(m.groups).sort()) named[k] = enc(m.groups[k]);
    out.named = named;
  }
  // `.indices` exists ONLY under the `d` (hasIndices) flag -- a [start,end] span per
  // group (undefined for a non-participating one, hence enc). Guarded so a non-`d`
  // match serializes byte-for-byte as before: this axis is pure new signal, catching
  // engines that return the same matched string from a different span.
  if (m.indices) {
    out.indices = Array.prototype.slice.call(m.indices).map(enc);
    if (m.indices.groups) {
      const ig = {};
      for (const k of Object.keys(m.indices.groups).sort()) ig[k] = enc(m.indices.groups[k]);
      out.indices_named = ig;
    }
  }
  return out;
}

// lastIndex preset battery (rationale: api_descriptors._LASTINDEX_PRESETS_JS).
function lastIndexPresets(s) {
  const seen = new Set(), out = [];
  for (const k of [0, 1, Math.floor(s.length / 2), s.length, s.length + 1]) { if (!seen.has(k)) { seen.add(k); out.push(k); } }
  return out;
}
function presetBattery(re, s, call) {
  if (!re.global && !re.sticky) return call();   // lastIndex dead -> value unchanged
  const out = {};
  for (const k of lastIndexPresets(s)) {
    re.lastIndex = k;
    out["preset_" + k] = {result: call(), lastIndex: re.lastIndex};
  }
  re.lastIndex = 0;
  return out;
}

try {
  const re = new RegExp(pattern, flags);
  let value;
  const t0 = performance.now();
  value = presetBattery(re, input, () => re.test(input));
  const t1 = performance.now();
  process.stdout.write(JSON.stringify({api: api, regex_id: regex_id, ok: true, value: value, exec_ms: t1 - t0}) + "\n");
} catch (e) {
  process.stdout.write(JSON.stringify({api: api, regex_id: regex_id, ok: false, error: (e && e.name) || String(e)}) + "\n");
}
