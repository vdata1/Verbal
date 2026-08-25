// provenance:
//   git_commit: 8dc8b1d3df8b1ea648b30d81a458e9014dd4c48a
//   config_sha: d769e16a7cda2f6d72eb588b3dd1b24c8759cce2d09f453fd00753e4632790bd
//   seed: 0
//   corpus: data/uniq-regexes-8.json
//   corpus_sha: 999fe71e83f0db26931d6810164bff9efefdf3f6791d3444aa770ccdafe280e9
//   stage: harness
//   api: exec
//   regex_id: regex_8576
//   flags: iu
"use strict";
const pattern = "(\\p{L})@";
const flags = "iu";
const input = "\ud88a\udfcf@";
const api = "exec";
const regex_id = "regex_8576";

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
  return out;
}

try {
  const re = new RegExp(pattern, flags);
  let value;
  const m = re.exec(input);
  value = serializeMatch(m);
  if (re.global || re.sticky) { value = {result: value, lastIndex: re.lastIndex}; }
  process.stdout.write(JSON.stringify({api: api, regex_id: regex_id, ok: true, value: value}) + "\n");
} catch (e) {
  process.stdout.write(JSON.stringify({api: api, regex_id: regex_id, ok: false, error: (e && e.name) || String(e)}) + "\n");
}
