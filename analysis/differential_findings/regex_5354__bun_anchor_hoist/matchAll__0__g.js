// provenance:
//   git_commit: 48defb5d8769b2ef2d7281b081b5277867f18115
//   config_sha: d769e16a7cda2f6d72eb588b3dd1b24c8759cce2d09f453fd00753e4632790bd
//   seed: 0
//   corpus: data/uniq-regexes-8.json
//   corpus_sha: 999fe71e83f0db26931d6810164bff9efefdf3f6791d3444aa770ccdafe280e9
//   stage: harness
//   api: matchAll
//   regex_id: regex_5354
//   flags: g
"use strict";
const pattern = "(.+)\\n(\\d{2}:\\d{2}:\\d{2},\\d{3} --> \\d{2}:\\d{2}:\\d{2},\\d{3})\\n((?:^.*$\\n)*?)\\n";
const flags = "g";
const input = "\nf/B\u000evO_,9\u001c\n00:05:92,848 --> 62:42:88,945\n!\\,f\u0005\n\n\nK\n02:04:29,720 --> 64:81:75,693\n\n\n";
const api = "matchAll";
const regex_id = "regex_5354";

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
  value = Array.from(input.matchAll(re)).map(serializeMatch);
  process.stdout.write(JSON.stringify({api: api, regex_id: regex_id, ok: true, value: value}) + "\n");
} catch (e) {
  process.stdout.write(JSON.stringify({api: api, regex_id: regex_id, ok: false, error: (e && e.name) || String(e)}) + "\n");
}
