// provenance:
//   git_commit: unknown-CalledProcessError
//   config_sha: d769e16a7cda2f6d72eb588b3dd1b24c8759cce2d09f453fd00753e4632790bd
//   seed: 0
//   corpus: data/uniq-regexes-8.json
//   corpus_sha: 999fe71e83f0db26931d6810164bff9efefdf3f6791d3444aa770ccdafe280e9
//   stage: harness
//   api: test
//   regex_id: regex_3872
//   flags: iu
"use strict";
const pattern = "[\\p{L}0-9]";
const flags = "iu";
const input = "\ud889\udf77";
const api = "test";
const regex_id = "regex_3872";

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
  value = re.test(input);
  process.stdout.write(JSON.stringify({api: api, regex_id: regex_id, ok: true, value: value}) + "\n");
} catch (e) {
  process.stdout.write(JSON.stringify({api: api, regex_id: regex_id, ok: false, error: (e && e.name) || String(e)}) + "\n");
}
