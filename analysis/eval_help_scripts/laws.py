#!/usr/bin/env python3
r"""Single-engine metamorphic laws: find bugs no differential test can, by construction.

WHY
---
Every oracle this project has is a comparison BETWEEN implementations, and such an oracle
is structurally incapable of finding a bug that every engine shares. It is also unable to
say who is right without a spec argument, because node and deno are both V8.

A law is different: it is a statement that must hold WITHIN one engine, whatever that
engine's opinion about anything else. `s.replace(re, "$&") === s` is true for every regex
and every string, in every conforming implementation. An engine that breaks it has a bug,
full stop -- no vote, no reference implementation, no second engine.

SOUNDNESS IS THE WHOLE GAME
---------------------------
An unsound law is worse than no law: it fires on every engine, on every input, and buries
the real signal. So each law below carries an explicit APPLICABILITY guard and every guard
is justified in a comment. Where a law is only conditionally sound it is marked heuristic
and reported in a separate bucket, never mixed with the sound ones.

The `sticky_anchored_slice` law is the reason this exists: `/.*x.*/y` on `"zzx"` returns
null in bun while `/^(?:.*x.*)/` on the same string matches -- so a KNOWN bug (the sticky
`.*` family, ~36% of window 12050-15050) is catchable with a single engine and no
comparison at all. That is the proof that the axis pays.

USAGE
-----
  laws.py --pattern '.*x.*' --flags '' --input zzx
  laws.py --sample 500 --results-root results
  laws.py --sample 300 --flags-contains v --pattern-contains '\p{'
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import random
import subprocess
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "eval"))

from run_eval import ENGINE_CMD, ENGINE_ENV, HARNESS_TIMEOUT_S   # noqa: E402

# Laws whose violation is unconditionally a bug, versus ones that are only conditionally
# sound. Reported apart so a heuristic can never be mistaken for a proof.
HEURISTIC_LAWS = {"sticky_anchored_slice"}

_LAWS_JS = r'''"use strict";
const pattern = __PATTERN__;
const flags   = __FLAGS__;
const input   = __INPUT__;

const results = {};
function law(name, applicable, fn) {
  if (!applicable) { results[name] = {skipped: true}; return; }
  try {
    const r = fn();
    results[name] = (r === true) ? {ok: true} : {ok: false, detail: r};
  } catch (e) {
    // A throw is NOT a law violation: constructing the regex may legitimately fail
    // (uv is a SyntaxError, matchAll needs g, ...). Record it and move on.
    results[name] = {ok: null, error: (e && e.name) || String(e)};
  }
}
// A fresh regex per law: `lastIndex` is shared mutable state, so reusing one object
// would make each law's result depend on the previous law's side effects.
const mk = (f) => new RegExp(pattern, f === undefined ? flags : f);
const base = mk();
const isGlobal = base.global, isSticky = base.sticky, hasIndices = base.hasIndices;
const noGY = flags.replace(/[gy]/g, "");

// Guards for the anchored-slice law, sharpened 2026-08-03 after a 400-case sweep showed
// the blunt version skipping 765 of 1179 evaluations.
//
// Slicing at k>0 destroys context that lookbehind, \b/\B and ^/$ read, so those patterns
// are only compared AT k=0 -- where `input.slice(0)` is the identity function and every
// one of those constructs therefore behaves identically on both sides. That is sound by
// construction, and recovers most of the skipped coverage.
//
// The `m` flag is different and stays a hard guard at every k: with `m`, the `^` this law
// PREPENDS matches at any line start, so "^(?:src)" no longer means "must begin at 0" and
// the two sides are asking different questions even at k=0.
const contextual = /\(\?<[=!]|\\b|\\B|\^|\$/.test(pattern);

// --- 1. replace with "$&" is the identity, for EVERY regex and input ---------
law("replace_identity", true, () => {
  const out = input.replace(mk(), "$&");
  return out === input ? true : {got: out, want: input};
});

// --- 2. test(s) is exactly "exec(s) is not null" ----------------------------
law("test_iff_exec", true, () => {
  const t = mk().test(input);
  const m = mk().exec(input);
  return t === (m !== null) ? true : {test: t, exec_null: m === null};
});

// --- 3. search(re) is the index of the first match ---------------------------
// NOT applicable to a sticky regex: exec is anchored at lastIndex while search scans,
// so they may legitimately disagree.
law("search_is_first_index", !isSticky, () => {
  const s = input.search(mk());
  const m = mk().exec(input);
  const want = m ? m.index : -1;
  return s === want ? true : {search: s, exec_index: want};
});

// --- 4. lastIndex lands exactly at the end of the match ----------------------
law("lastindex_at_match_end", isGlobal || isSticky, () => {
  const re = mk();
  const m = re.exec(input);
  if (m === null) return true;                       // vacuous, not a violation
  const want = m.index + m[0].length;
  return re.lastIndex === want ? true : {lastIndex: re.lastIndex, want: want};
});

// --- 5. `d` spans must actually address the matched text ---------------------
law("indices_address_match", hasIndices, () => {
  const m = mk().exec(input);
  if (m === null || !m.indices) return true;
  for (let i = 0; i < m.length; i++) {
    const span = m.indices[i];
    if (m[i] === undefined) {
      if (span !== undefined) return {group: i, expected_undefined_span: span};
      continue;
    }
    if (span === undefined) return {group: i, missing_span_for: m[i]};
    const sliced = input.slice(span[0], span[1]);
    if (sliced !== m[i]) return {group: i, span: span, sliced: sliced, group_text: m[i]};
  }
  return true;
});

// --- 6. matchAll indices are strictly increasing -----------------------------
// Sound even for zero-length matches: the engine must advance lastIndex, so the next
// match cannot start where the previous one did.
law("matchall_monotonic", isGlobal, () => {
  const ms = Array.from(input.matchAll(mk()));
  for (let i = 1; i < ms.length; i++) {
    if (!(ms[i].index > ms[i - 1].index)) {
      return {at: i, prev_index: ms[i - 1].index, index: ms[i].index};
    }
  }
  return true;
});

// --- 7. match() without g is exec() ------------------------------------------
law("match_is_exec", !isGlobal, () => {
  const a = input.match(mk(noGY));
  const b = mk(noGY).exec(input);
  const ser = (m) => m === null ? null
      : JSON.stringify([m[0], m.index, Array.prototype.slice.call(m, 1)]);
  return ser(a) === ser(b) ? true : {match: ser(a), exec: ser(b)};
});

// --- 8. HEURISTIC: sticky at lastIndex k == anchored match on the slice -------
// A sticky match must BEGIN at lastIndex. Anchoring the same source with ^ and matching
// the suffix from k is the same question asked a different way -- so the two must agree
// on whether a match exists and on what it matches.
law("sticky_anchored_slice", flags.indexOf("m") < 0, () => {
  const anchored = new RegExp("^(?:" + pattern + ")", noGY);
  const ks = contextual ? [0] : [0, 1, Math.floor(input.length / 2)];
  for (const k of ks) {
    if (k > input.length) continue;
    const re = mk(noGY + "y");
    re.lastIndex = k;
    const a = re.exec(input);
    const b = anchored.exec(input.slice(k));
    const am = a ? a[0] : null, bm = b ? b[0] : null;
    if (am !== bm) return {lastIndex: k, sticky: am, anchored: bm};
  }
  return true;
});

process.stdout.write(JSON.stringify({ok: true, laws: results}) + "\n");
'''


def build_laws_harness(pattern: str, flags: str, string: str) -> str:
    js = _LAWS_JS
    js = js.replace("__PATTERN__", json.dumps(pattern))
    js = js.replace("__FLAGS__", json.dumps(flags))
    js = js.replace("__INPUT__", json.dumps(string))
    return js


def run_laws(engine: str, pattern: str, flags: str, string: str) -> dict | None:
    """Evaluate every law in one engine. None if the engine produced no envelope."""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(build_laws_harness(pattern, flags, string))
        path = fh.name
    try:
        overlay = ENGINE_ENV.get(engine)
        proc = subprocess.run(
            ENGINE_CMD[engine] + [path], capture_output=True, text=True,
            timeout=HARNESS_TIMEOUT_S,
            env={**os.environ, **overlay} if overlay else None)
    except subprocess.TimeoutExpired:
        return None
    finally:
        os.unlink(path)
    for line in proc.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "laws" in obj:
            return obj["laws"]
    return None


# --- harness-derived case selection ------------------------------------------

def _case_from_harness(path: str) -> tuple[str, str, str] | None:
    """`(pattern, flags, input)` read out of a generated harness's own consts."""
    want = {"const pattern = ": None, "const flags = ": None, "const input = ": None}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                for key in want:
                    if want[key] is None and line.startswith(key):
                        want[key] = json.loads(line[len(key):].rstrip().rstrip(";"))
                if all(v is not None for v in want.values()):
                    break
    except (OSError, json.JSONDecodeError):
        return None
    if any(v is None for v in want.values()):
        return None
    return (want["const pattern = "], want["const flags = "], want["const input = "])


def _select(args) -> list[str]:
    root = args.results_root
    dirs = [os.path.join(root, args.regex)] if args.regex else sorted(
        glob.glob(os.path.join(root, "regex_*")))
    if args.pattern_contains:
        kept = []
        for d in dirs:
            probe = next(iter(sorted(glob.glob(os.path.join(d, "*__*__*.js")))), None)
            if probe is None:
                continue
            case = _case_from_harness(probe)
            if case and args.pattern_contains in case[0]:
                kept.append(d)
        dirs = kept
    paths = []
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*__*__*.js")):
            if args.flags_contains:
                fl = os.path.basename(f).rsplit("__", 1)[1][:-3]
                if not all(ch in fl for ch in args.flags_contains):
                    continue
            paths.append(f)
    paths.sort()
    if args.sample and len(paths) > args.sample:
        random.Random(args.seed).shuffle(paths)
        paths = sorted(paths[:args.sample])
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pattern")
    ap.add_argument("--flags", default="")
    ap.add_argument("--input")
    ap.add_argument("--results-root", default="results")
    ap.add_argument("--regex")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--flags-contains")
    ap.add_argument("--pattern-contains")
    ap.add_argument("--engines", default="node,bun,deno")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]

    if args.pattern is not None and args.input is not None:
        cases = [(args.pattern, args.flags, args.input, "<cli>")]
    else:
        paths = _select(args)
        if not paths:
            sys.exit("no harnesses matched -- check --results-root / filters")
        cases = []
        for p in paths:
            c = _case_from_harness(p)
            if c:
                cases.append((*c, p))

    covered = sorted({os.path.basename(os.path.dirname(c[3])) for c in cases
                      if c[3] != "<cli>"})
    print(f"checking {len(cases)} cases across {len(covered) or 1} regexes "
          f"x {len(engines)} engines", flush=True)
    if args.dry_run:
        print("  (dry run -- no engines executed)")
        return

    t0 = time.monotonic()
    violations, errors = [], 0
    tally: dict[str, dict[str, int]] = {}
    for pattern, flags, string, src in cases:
        for engine in engines:
            laws = run_laws(engine, pattern, flags, string)
            if laws is None:
                errors += 1
                continue
            for name, r in laws.items():
                slot = tally.setdefault(name, {"ok": 0, "violated": 0, "skipped": 0,
                                               "error": 0})
                if r.get("skipped"):
                    slot["skipped"] += 1
                elif r.get("ok") is True:
                    slot["ok"] += 1
                elif r.get("ok") is None:
                    slot["error"] += 1
                else:
                    slot["violated"] += 1
                    v = {"law": name, "engine": engine, "pattern": pattern,
                         "flags": flags, "input": string, "detail": r.get("detail"),
                         "source": src,
                         "heuristic": name in HEURISTIC_LAWS}
                    violations.append(v)
                    kind = "HEURISTIC" if v["heuristic"] else "LAW VIOLATION"
                    print(f"  !! {kind} {name} [{engine}] /{pattern}/{flags} "
                          f"input={string!r}", flush=True)
                    print(f"       {json.dumps(r.get('detail'))[:160]}", flush=True)

    elapsed = time.monotonic() - t0
    sound = [v for v in violations if not v["heuristic"]]
    heur = [v for v in violations if v["heuristic"]]
    out = {"cases": len(cases), "engines": engines,
           "distinct_regexes": len(covered),
           "law_tally": tally,
           "sound_violations": sound, "heuristic_violations": heur,
           "engine_errors": errors, "elapsed_s": round(elapsed, 1)}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    print("=" * 60)
    print(f"cases:                  {len(cases)} across {len(covered) or 1} regexes")
    print(f"SOUND LAW VIOLATIONS:   {len(sound)}   [each is a definite engine bug]")
    print(f"heuristic violations:   {len(heur)}   [guarded, but verify before reporting]")
    print(f"engine errors/timeouts: {errors}")
    for name, slot in sorted(tally.items()):
        print(f"    {name:26} ok={slot['ok']:<6} violated={slot['violated']:<5} "
              f"skipped={slot['skipped']:<6} err={slot['error']}")
    print(f"elapsed: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
