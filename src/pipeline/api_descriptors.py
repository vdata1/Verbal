"""Per-API descriptors -- pure declarative data, no per-API code in the core.

Each of the eight JS RegExp/String APIs under test is ONE frozen ``ApiDescriptor`` row.
The specializer (Stage 2) and the harness synthesizer (Stage 3) read only these
fields; neither ever branches on ``descriptor.api``. Adding an API = adding a row.
Changing how a knob is realized = editing the core, applied to every row at once.

Settled shape: [[july 6 per-API descriptor shape (settled)]].

Fidelity contract (the whole point of the project): each synthesized harness
prints exactly ONE canonical JSON line to stdout --
``{api, regex_id, ok:true, value, exec_ms}`` on success, or
``{api, regex_id, ok:false, error:<name>}`` if constructing/using the regex
throws. ``value`` is serialized identically across engines by construction (same
skeleton), so any byte difference in ``value`` is a real engine discrepancy. A
thrown regex error is a COMPARABLE outcome; a process crash / missing JSON line
is a run defect handled by the eval runner, not here.

``exec_ms`` is the ReDoS signal: ``performance.now()` around the oracle body ONLY,
so it excludes engine startup and process spawn (which dwarf the regex itself) and
excludes ``new RegExp`` compilation. It is deliberately NOT part of the comparable
outcome -- timing is nondeterministic, and ``run_eval._comparable`` selects only
``ok``/``value``/``error``, so a slow run can never fake a value discrepancy. The
error path carries no ``exec_ms``: a throw has no meaningful execution time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiDescriptor:
    api: str                          # exec|test|matchAll|replace|split|match|search|replaceAll
    required_flags: str               # flags the regex MUST carry for this API

    # --- Stage 2 specialization knobs (core realizes each uniformly) ---------
    min_matches: int                  # min non-overlapping matches the string must contain
    filler_between: bool              # non-matching filler around/between matches
    groups_must_participate: bool     # every capture group matches >= 1x
    extra_constraints: tuple[str, ...]  # extra `where` clauses appended verbatim
    extra_helpers: tuple[str, ...]      # `def`s those clauses reference

    # --- Stage 3 harness synthesis -------------------------------------------
    template: str                     # JS harness with __PATTERN__/__FLAGS__/... tokens
    oracle: str                       # JS snippet (baked into template) computing `value`


# --- Shared JS harness skeleton ----------------------------------------------
# ONE skeleton for all eight APIs. Per-string values are substituted in Stage 3 by
# replacing the __PATTERN__/__FLAGS__/__INPUT__/__API__/__REGEX_ID__ tokens (plain
# string replacement, not str.format -- JS is full of braces). The API-specific
# oracle body is baked into __ORACLE__ at descriptor-construction time below, so
# the skeleton stays single-sourced and the Stage 3 core never sees the API name.
#
# `enc` makes serialization deterministic and undefined-aware: a non-participating
# capture group is `undefined` in JS, which JSON.stringify would silently drop (in
# objects) or coerce to null (in arrays). We map it to an explicit sentinel so
# byte-equality of `value` is a sound diff.
_SKELETON = r'''__PROVENANCE__"use strict";
const pattern = __PATTERN__;
const flags = __FLAGS__;
const input = __INPUT__;
const api = __API__;
const regex_id = __REGEX_ID__;

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
  for (const k of __LASTINDEX_PRESETS__) { if (!seen.has(k)) { seen.add(k); out.push(k); } }
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
__ORACLE__
  const t1 = performance.now();
  process.stdout.write(JSON.stringify({api: api, regex_id: regex_id, ok: true, value: value, exec_ms: t1 - t0}) + "\n");
} catch (e) {
  process.stdout.write(JSON.stringify({api: api, regex_id: regex_id, ok: false, error: (e && e.name) || String(e)}) + "\n");
}
'''

# Fixed, uniform batteries (same for every regex). Tokens/limits that don't apply
# to a given regex still run -- engines must agree on those too (settled doc).
# The ambiguous tokens are where engines actually differ:
# $12 with <2 groups ($1 then "2", or group 12?), $0 (not special), $99 (no such
# group), $<nosuchname> (empty vs literal), $<> (empty name), and a dangling $ (literal).
_REPLACE_TOKENS = ["[$&]", "[$`]", "[$']", "[$$]", "[$1]", "[$<name>]",
                   "[$12]", "[$0]", "[$99]", "[$<nosuchname>]", "[$<>]", "[$]"]
# undefined = no limit. The added values exercise ToUint32 coercion, a classic bug
# farm: -1 -> 4294967295 (unlimited), 2**32 -> 0 (returns []), 2**32-1, 1.5 -> 1,
# NaN -> 0, "2" -> 2. Keys are `limit_<String(L)>`, all distinct, insertion-ordered.
_SPLIT_LIMITS_JS = '[undefined, 0, 1, 1000000, -1, 2**32, 2**32 - 1, 1.5, NaN, "2"]'
# lastIndex presets for a stateful (`g`/`y`) regex, as a JS expression over the input
# `s` so one rule scales to any length: start, just past start, middle, exactly at the
# end, and past the end (the spec edge, where there is no match and lastIndex resets
# to 0). Under g/y, lastIndex is where the next match starts, making it an input the
# harness controls rather than a constant 0.
#
# `presetBattery` records both the outcome and the lastIndex the call left behind.
# The latter is the point: it is the only way to observe laws about state after the
# call, which no value comparison can reach --
#   * `Symbol.search` must save and restore lastIndex;
#   * `Symbol.match` with `g` must reset lastIndex to 0 before collecting.
# Applied to the read-only APIs only. replace/replaceAll own a per-token reset and
# split never touches lastIndex (`Symbol.split` uses an internal clone); all three
# carry their own batteries, which presets would cross-multiply for no new law.
#
# Kept terse on the JS side: the skeleton is copied verbatim into every harness file a
# window generates, so a paragraph of JS comment is duplicated millions of times.
_LASTINDEX_PRESETS_JS = '[0, 1, Math.floor(s.length / 2), s.length, s.length + 1]'

# --- Per-API oracle snippets (JS, indented to sit inside the try block) ------
_ORACLE = {
    # exec -> [match, ...groups, index]. Under g/y this becomes the lastIndex preset
    # battery: `preset_0` subsumes the old {result, lastIndex} observation exactly, and
    # the other presets are the start positions this API never ran from.
    "exec": (
        "  value = presetBattery(re, input, () => serializeMatch(re.exec(input)));\n"
    ),
    # test -> boolean. Stateful under g/y for the same reason exec is (both go through
    # RegExpExec), so it gets the same battery.
    "test": (
        "  value = presetBattery(re, input, () => re.test(input));\n"
    ),
    # matchAll -> array of match objects. Requires `g`; without it matchAll throws
    # -> caught as {error} (a comparable outcome), not a skip. Always stateful, so
    # always batteried: matchAll CLONES its regex, and the clone inherits lastIndex,
    # so where the iteration starts is exactly what the presets vary.
    "matchAll": (
        "  value = presetBattery(re, input, () => Array.from(input.matchAll(re)).map(serializeMatch));\n"
    ),
    # replace -> object {token -> resulting string} over the fixed battery, plus a
    # function replacer that JSON-stringifies its (undefined-encoded) arguments.
    # Insertion order is fixed, so JSON key order is deterministic across engines.
    "replace": (
        "  const tokens = __REPL_TOKENS__;\n"
        "  value = {};\n"
        # Reset lastIndex before every call: `re` is reused across the token battery, and
        # a STICKY (non-global) regex carries lastIndex between calls, making each token's
        # result depend on the previous one's match end -- order-dependent, and divergent
        # across engines. A no-op for non-sticky regexes (lastIndex is always 0), so this
        # measures each token as an independent replace(input, token) from a clean state.
        "  for (const t of tokens) { re.lastIndex = 0; value[t] = input.replace(re, t); }\n"
        "  re.lastIndex = 0;\n"
        "  value['__fn__'] = input.replace(re, function() {\n"
        "    return '[' + JSON.stringify(Array.prototype.slice.call(arguments).map(enc)) + ']';\n"
        "  });\n"
    ),
    # split -> {default, limit_<L>...} over the fixed LIMIT set. undefined limit
    # means no limit. Group captures in the separator can yield undefined -> enc.
    "split": (
        "  value = {default: input.split(re).map(enc)};\n"
        "  for (const L of __SPLIT_LIMITS__) { value['limit_' + String(L)] = input.split(re, L).map(enc); }\n"
    ),
    # String.prototype.match -> a DUAL shape nothing else has: WITHOUT g, a match
    # object like exec (index + groups); WITH g, a flat array of matched substrings
    # (no index, no groups). Both serialize deterministically.
    # Under g, `Symbol.match` is spec'd to RESET lastIndex to 0 before collecting, so
    # every preset must give the same result and leave lastIndex at 0 -- a law the
    # battery checks directly, and one no cross-engine value diff could ever see.
    "match": (
        "  value = presetBattery(re, input, () => {\n"
        "    const m = input.match(re);\n"
        "    return re.global ? m : serializeMatch(m);\n"
        "  });\n"
    ),
    # String.prototype.search -> the index of the first match (-1 if none); ignores g.
    # An index-returning API no other surface here has. `Symbol.search` must SAVE AND
    # RESTORE lastIndex -- a documented divergence area, and now observable: under g/y
    # the battery presets lastIndex to k and records what the call left, which a
    # conforming engine returns as k for every preset while the result never moves.
    "search": (
        "  value = presetBattery(re, input, () => input.search(re));\n"
    ),
    # String.prototype.replaceAll -> shares replace's token battery but THROWS
    # TypeError unless the regex is global -- which is its whole reason to exist
    # separate from replace+g. required_flags="" (below) so the non-g variants
    # exercise that throw as a comparable {error} outcome under every flag combo,
    # and the g variant exercises replace-all.
    "replaceAll": (
        "  const tokens = __REPL_TOKENS__;\n"
        "  value = {};\n"
        # replaceAll requires global (else TypeError), and global self-resets lastIndex;
        # the reset is thus a no-op here, kept for symmetry with `replace` and to stay
        # correct if the required-flags choice ever changes.
        "  for (const t of tokens) { re.lastIndex = 0; value[t] = input.replaceAll(re, t); }\n"
        "  re.lastIndex = 0;\n"
        "  value['__fn__'] = input.replaceAll(re, function() {\n"
        "    return '[' + JSON.stringify(Array.prototype.slice.call(arguments).map(enc)) + ']';\n"
        "  });\n"
    ),
}


def _build_template(api: str) -> str:
    """Bake the API's oracle (+ batteries) into the shared skeleton, leaving the
    per-string tokens (__PATTERN__ etc.) and __PROVENANCE__ for Stage 3."""
    oracle = _ORACLE[api]
    oracle = oracle.replace("__REPL_TOKENS__", json.dumps(_REPLACE_TOKENS))
    oracle = oracle.replace("__SPLIT_LIMITS__", _SPLIT_LIMITS_JS)
    skeleton = _SKELETON.replace("__LASTINDEX_PRESETS__", _LASTINDEX_PRESETS_JS)
    return skeleton.replace("__ORACLE__", oracle.rstrip("\n"))


# --- The five rows -----------------------------------------------------------
DESCRIPTORS: tuple[ApiDescriptor, ...] = (
    ApiDescriptor(
        api="exec", required_flags="",
        min_matches=1, filler_between=False, groups_must_participate=True,
        extra_constraints=(), extra_helpers=(),
        template=_build_template("exec"), oracle=_ORACLE["exec"],
    ),
    ApiDescriptor(
        api="test", required_flags="",
        min_matches=1, filler_between=False, groups_must_participate=False,
        extra_constraints=(), extra_helpers=(),
        template=_build_template("test"), oracle=_ORACLE["test"],
    ),
    ApiDescriptor(
        api="matchAll", required_flags="g",
        min_matches=2, filler_between=True, groups_must_participate=False,
        extra_constraints=(), extra_helpers=(),
        template=_build_template("matchAll"), oracle=_ORACLE["matchAll"],
    ),
    ApiDescriptor(
        api="replace", required_flags="",
        min_matches=1, filler_between=False, groups_must_participate=False,
        extra_constraints=(), extra_helpers=(),
        template=_build_template("replace"), oracle=_ORACLE["replace"],
    ),
    ApiDescriptor(
        api="split", required_flags="",
        min_matches=1, filler_between=False, groups_must_participate=False,
        extra_constraints=(), extra_helpers=(),
        template=_build_template("split"), oracle=_ORACLE["split"],
    ),
    # match mirrors exec's specialization (a participating-group match to exercise the
    # non-g match-object shape); the g variant then exercises the flat-array shape.
    ApiDescriptor(
        api="match", required_flags="",
        min_matches=1, filler_between=False, groups_must_participate=True,
        extra_constraints=(), extra_helpers=(),
        template=_build_template("match"), oracle=_ORACLE["match"],
    ),
    ApiDescriptor(
        api="search", required_flags="",
        min_matches=1, filler_between=False, groups_must_participate=False,
        extra_constraints=(), extra_helpers=(),
        template=_build_template("search"), oracle=_ORACLE["search"],
    ),
    # replaceAll: required_flags="" so the non-g variants test the TypeError-unless-
    # global rule; >=2 matches + filler so the g variant meaningfully replaces ALL.
    ApiDescriptor(
        api="replaceAll", required_flags="",
        min_matches=2, filler_between=True, groups_must_participate=False,
        extra_constraints=(), extra_helpers=(),
        template=_build_template("replaceAll"), oracle=_ORACLE["replaceAll"],
    ),
)

DESCRIPTORS_BY_API = {d.api: d for d in DESCRIPTORS}
