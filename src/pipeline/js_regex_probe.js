"use strict";
// JS-regex validity probe (reference gate for the pipeline).
//
// Reads a JSON array of {src, flags} objects from the file named in argv[2] and
// prints one JSON line per entry: {"i": <index>, "valid": <bool>, "error": <name|null>}.
//
// Validity is tested with `new RegExp(src, flags)` under the SAME construction-
// affecting flags the pipeline's harnesses will actually use for this pattern (its
// `requires_flags`, in practice `u` -- the only flag besides the out-of-scope `v`
// that changes escape strictness; see js_construction_flags). A pattern admitted
// here is one every harness can construct; a pattern that throws here would throw in
// every harness on every engine, so it is out of scope (not_js) -- never recorded
// `ok` and run to a guaranteed SyntaxError.
//
// (Historically this probe validated with NO flags, on the assumption the harness
// used none that affect construction. The `u`-requiring specializer broke that
// invariant -- a `\p{...}` pattern constructs unflagged as literal escapes but throws
// under the `/u` the harness carries. See EXPERIMENT_GAPS G1.)
const fs = require("fs");
const entries = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
for (let i = 0; i < entries.length; i++) {
  const entry = entries[i];
  let valid = true, error = null;
  try {
    new RegExp(entry.src, entry.flags || "");
  } catch (e) {
    valid = false;
    error = (e && e.name) || String(e);
  }
  process.stdout.write(JSON.stringify({i: i, valid: valid, error: error}) + "\n");
}
