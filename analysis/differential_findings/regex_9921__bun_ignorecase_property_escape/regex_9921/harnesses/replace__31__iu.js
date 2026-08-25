// provenance:
//   git_commit: d1f3125c84c1c81f43f55d20385a5c05f5890765
//   config_sha: 04a28699a633d748d52433ff4cd285b881c674c46cb43ddb8b1c5d0d1d8afca3
//   seed: 0
//   corpus: data/uniq-regexes-8.json
//   corpus_sha: 999fe71e83f0db26931d6810164bff9efefdf3f6791d3444aa770ccdafe280e9
//   stage: harness
//   api: replace
//   regex_id: regex_9921
//   flags: iu
"use strict";
const pattern = "\\p{Uppercase_Letter}";
const flags = "iu";
const input = "a\ud835\udde3";
const api = "replace";
const regex_id = "regex_9921";

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
  const tokens = ["[$&]", "[$`]", "[$']", "[$$]", "[$1]", "[$<name>]"];
  value = {};
  for (const t of tokens) { value[t] = input.replace(re, t); }
  value['__fn__'] = input.replace(re, function() {
    return '[' + JSON.stringify(Array.prototype.slice.call(arguments).map(enc)) + ']';
  });
  process.stdout.write(JSON.stringify({api: api, regex_id: regex_id, ok: true, value: value}) + "\n");
} catch (e) {
  process.stdout.write(JSON.stringify({api: api, regex_id: regex_id, ok: false, error: (e && e.name) || String(e)}) + "\n");
}
