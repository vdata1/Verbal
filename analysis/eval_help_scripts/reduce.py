#!/usr/bin/env python3
r"""Reduce a differential finding to a minimal (api, pattern, flags, input) repro.

WHY THIS EXISTS
---------------
A window's headline counts per-(regex x string x flag x api) CELLS, so one engine fact
books hundreds of them -- the 12050-15050 window booked 3772 discrepancies across 42
regexes for what triage showed to be a handful of distinct bugs. `dedupe_headline.py`
collapses cells into clusters keyed by (regex, kind, engine partition), which helps, but
it still reports one bug once per corpus regex that witnesses it: the `matchAll`+`gv`
surrogate bug rendered as 34 "unrelated patterns" because the key includes the pattern.

Reduction attacks that at the root. Two corpus witnesses that reduce to the SAME minimal
repro are the same bug, whatever their original patterns looked like. So this tool is both
the thing that turns a finding into a file-ready one-liner AND the thing that makes dedup
mean something (Klees et al., CCS 2018: count bugs, not crashes).

FIDELITY
--------
The reducer must observe exactly what the pipeline observes, or a "reduction" could
preserve a different phenomenon than the one that was found. So it reuses the pipeline's
own machinery rather than reimplementing it:

  * the harness JS comes from `ApiDescriptor.template` (the same template Stage 3 fills),
  * `_extract_canonical` / `_comparable` are imported from `eval/run_eval.py`,
  * `ENGINE_CMD` is imported too, so engine invocation cannot drift.

The only difference from a pipeline harness is that `__PROVENANCE__` is filled with "" --
a comment block, so the EXECUTABLE JS is byte-identical.

THE INVARIANT
-------------
Interestingness is "still a value discrepancy AND the same engine partition". Partition,
not just "some difference": without it, ddmin happily walks from a bun-vs-V8 bug to an
unrelated deno-vs-rest one and reports a minimal repro for a bug you were not reducing.

USAGE
-----
  # one case, given directly
  reduce.py --api exec --pattern '([\s\t\p{Zl}\p{C}\p{Zp}])' --flags v --input <str>

  # one case, pulled out of a stored diff artifact
  reduce.py --from-diff results/regex_14680/exec.diff.json --n 0 --flags v

  # every discrepancy in a headline, reduced and then deduplicated
  reduce.py --headline results/eval_headline_12050_15050.json --limit 50 \
            --out results/reduced_12050_15050.json

Runs inside the container (needs node/bun/deno). See analysis/PLAN_2026-08-03.md for the
dev-worktree docker recipe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "eval"))

from pipeline.api_descriptors import DESCRIPTORS_BY_API          # noqa: E402
from run_eval import ENGINE_CMD, _comparable, _extract_canonical  # noqa: E402

DEFAULT_ENGINES = ("node", "bun", "deno")

# Preference order for the API-simplification pass: earliest that still reproduces wins.
# `exec` first because its output (match + groups + index) is the most informative thing
# to paste into a bug report; `test` is smaller but says only true/false.
API_PREFERENCE = ("exec", "test", "search", "match", "matchAll", "split",
                  "replace", "replaceAll")

# Reduction is for VALUE discrepancies. A pathological-backtracking case is a different
# artifact (the ReDoS queue), and chasing one here would just burn the budget on timeouts,
# so the per-run budget is deliberately far below the pipeline's 20s.
DEFAULT_TIMEOUT_S = 5.0


class Budget:
    """Hard cap on engine invocations, so a pathological reduction cannot run forever."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def spend(self, n: int = 1) -> None:
        self.used += n
        if self.used > self.limit:
            raise BudgetExhausted(f"engine-run budget {self.limit} exhausted")


class BudgetExhausted(RuntimeError):
    pass


# --- Observation -------------------------------------------------------------

def build_harness(api: str, pattern: str, flags: str, string: str) -> str:
    """The pipeline's own harness for this case, minus the provenance comment block."""
    d = DESCRIPTORS_BY_API[api]
    js = d.template
    js = js.replace("__PROVENANCE__", "")
    js = js.replace("__PATTERN__", json.dumps(pattern))
    js = js.replace("__FLAGS__", json.dumps(flags))
    js = js.replace("__INPUT__", json.dumps(string))
    js = js.replace("__API__", json.dumps(api))
    js = js.replace("__REGEX_ID__", json.dumps("reduce"))
    return js


class Observer:
    """Runs cases across engines, with a memo table.

    ddmin re-tests the same candidate constantly (complements of overlapping subsets), so
    the cache is not an optimization detail -- it typically cuts engine spawns by >50%.
    """

    def __init__(self, engines: tuple[str, ...], timeout: float, budget: Budget) -> None:
        self.engines = engines
        self.timeout = timeout
        self.budget = budget
        self._cache: dict[tuple, dict] = {}

    def observe(self, case: tuple[str, str, str, str]) -> dict:
        """`(api, pattern, flags, input)` -> `{engine: comparable-or-None}`."""
        if case in self._cache:
            return self._cache[case]
        api, pattern, flags, string = case
        js = build_harness(api, pattern, flags, string)
        out: dict[str, str | None] = {}
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(js)
            path = fh.name
        try:
            for engine in self.engines:
                self.budget.spend()
                try:
                    proc = subprocess.run(ENGINE_CMD[engine] + [path],
                                          capture_output=True, text=True,
                                          timeout=self.timeout)
                    canonical = _extract_canonical(proc.stdout)
                except subprocess.TimeoutExpired:
                    canonical = None
                out[engine] = _comparable(canonical) if canonical is not None else None
        finally:
            os.unlink(path)
        self._cache[case] = out
        return out


def signature(obs: dict) -> tuple:
    """Canonical engine PARTITION: which engines agreed with which.

    `None` (defect / timeout / no envelope) is its own bucket rather than being dropped,
    so "bun crashed" can never be silently reduced into "bun disagreed".
    """
    groups: dict[str | None, list[str]] = {}
    for engine, comparable in obs.items():
        groups.setdefault(comparable, []).append(engine)
    return tuple(sorted(tuple(sorted(v)) for v in groups.values()))


def is_discrepancy(obs: dict) -> bool:
    """True iff at least two engines produced DIFFERENT comparable outcomes."""
    produced = {c for c in obs.values() if c is not None}
    return len(produced) > 1


class Oracle:
    """`interesting(case)` -- still the same bug, or not."""

    def __init__(self, observer: Observer, target_sig: tuple) -> None:
        self.observer = observer
        self.target = target_sig

    def interesting(self, case: tuple[str, str, str, str]) -> bool:
        try:
            obs = self.observer.observe(case)
        except BudgetExhausted:
            raise
        return is_discrepancy(obs) and signature(obs) == self.target


# --- Generic ddmin -----------------------------------------------------------

def ddmin(seq: list, test) -> list:
    """Classic delta debugging (Zeller & Hildebrandt, TSE 2002): a 1-minimal subsequence.

    `test(subsequence) -> bool`. Returns the shortest subsequence found for which `test`
    still holds; 1-minimal means removing any single remaining element breaks it.
    """
    if not seq:
        return seq
    n = 2
    while len(seq) >= 2:
        chunk = max(1, len(seq) // n)
        chunks = [seq[i:i + chunk] for i in range(0, len(seq), chunk)]

        # Prefer complements (removing a whole chunk) -- they shrink fastest.
        reduced = False
        for i in range(len(chunks)):
            complement = [x for j, c in enumerate(chunks) if j != i for x in c]
            if complement and test(complement):
                seq = complement
                n = max(n - 1, 2)
                reduced = True
                break
        if reduced:
            continue

        # Then single chunks (keeping only one).
        for c in chunks:
            if c and len(c) < len(seq) and test(c):
                seq = c
                n = 2
                reduced = True
                break
        if reduced:
            continue

        if n >= len(seq):
            break
        n = min(len(seq), n * 2)

    # Final 1-minimality sweep: try dropping each remaining element on its own, INCLUDING
    # the last one. The loop above exits at len(seq) < 2, so a single-element sequence is
    # returned without ever being tested for removal -- which means the empty set is never
    # reached. Measured cost of that omission: the split corollary of the sticky bug came
    # back as FIVE mechanism clusters (flags "", d, g, i, m) instead of one, because `""`
    # witnesses it but a 1-char flag string could never reduce to `""`.
    i = 0
    while i < len(seq):
        candidate = seq[:i] + seq[i + 1:]
        if test(candidate):
            seq = candidate
        else:
            i += 1
    return seq


# --- Pattern tokenization ----------------------------------------------------

def tokenize_pattern(p: str) -> list[str]:
    """Split a regex source into atomic tokens: escapes, char classes, and single chars.

    Character classes stay ONE token here (reducing inside them is a separate pass) --
    otherwise ddmin would routinely produce `[a-` and every candidate would be a
    SyntaxError, wasting the whole budget on uncompilable patterns.
    """
    toks: list[str] = []
    i = 0
    while i < len(p):
        c = p[i]
        if c == "\\" and i + 1 < len(p):
            # \p{...} / \u{...} / \k<...> keep their braces; everything else is 2 chars.
            if i + 2 < len(p) and p[i + 1] in "pPu" and p[i + 2] == "{":
                close = p.find("}", i + 2)
                if close != -1:
                    toks.append(p[i:close + 1])
                    i = close + 1
                    continue
            toks.append(p[i:i + 2])
            i += 2
        elif c == "[":
            j = i + 1
            if j < len(p) and p[j] == "^":
                j += 1
            if j < len(p) and p[j] == "]":     # leading ] is a literal
                j += 1
            while j < len(p) and p[j] != "]":
                j += 2 if p[j] == "\\" else 1
            toks.append(p[i:min(j + 1, len(p))])
            i = min(j + 1, len(p))
        else:
            toks.append(c)
            i += 1
    return toks


def class_members(cls: str) -> tuple[str, str, list[str]] | None:
    """Split `[^abc]` into (`[^`, `]`, ['a','b','c']). None if not a class."""
    if not (cls.startswith("[") and cls.endswith("]") and len(cls) >= 2):
        return None
    body = cls[1:-1]
    prefix = "["
    if body.startswith("^"):
        prefix, body = "[^", body[1:]
    members: list[str] = []
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            if i + 2 < len(body) and body[i + 1] in "pPu" and body[i + 2] == "{":
                close = body.find("}", i + 2)
                if close != -1:
                    members.append(body[i:close + 1])
                    i = close + 1
                    continue
            members.append(body[i:i + 2])
            i += 2
        else:
            # Keep `a-z` together: splitting a range yields `a-` or `-z`, which are
            # either SyntaxErrors or silently different patterns.
            if i + 2 < len(body) and body[i + 1] == "-" and body[i + 2] != "]":
                members.append(body[i:i + 3])
                i += 3
            else:
                members.append(body[i])
                i += 1
    return prefix, "]", members


# --- Reduction passes --------------------------------------------------------

def reduce_input(case, oracle: Oracle):
    api, pattern, flags, string = case
    chars = ddmin(list(string),
                  lambda sub: oracle.interesting((api, pattern, flags, "".join(sub))))
    return (api, pattern, flags, "".join(chars))


def reduce_pattern_tokens(case, oracle: Oracle):
    api, pattern, flags, string = case
    toks = tokenize_pattern(pattern)
    kept = ddmin(toks,
                 lambda sub: oracle.interesting((api, "".join(sub), flags, string)))
    return (api, "".join(kept), flags, string)


def reduce_class_members(case, oracle: Oracle):
    """ddmin the members of each character class in the pattern, one class at a time."""
    api, pattern, flags, string = case
    while True:
        toks = tokenize_pattern(pattern)
        changed = False
        for idx, tok in enumerate(toks):
            parsed = class_members(tok)
            if parsed is None or len(parsed[2]) < 2:
                continue
            prefix, suffix, members = parsed

            def rebuild(sub, _i=idx, _p=prefix, _s=suffix, _t=toks):
                head = _t[:_i] + [_p + "".join(sub) + _s] + _t[_i + 1:]
                return "".join(head)

            kept = ddmin(members,
                         lambda sub: bool(sub) and oracle.interesting(
                             (api, rebuild(sub), flags, string)))
            if len(kept) < len(members):
                pattern = rebuild(kept)
                changed = True
                break
        if not changed:
            return (api, pattern, flags, string)


def unwrap_groups(case, oracle: Oracle):
    """Try deleting group parentheses: `(?:X)`/`(X)`/`(?<n>X)` -> `X`.

    Done as an explicit pass rather than left to token ddmin because dropping ONE paren
    is always a SyntaxError -- ddmin would have to remove both in the same step, which it
    only does by luck.
    """
    api, pattern, flags, string = case
    changed = True
    while changed:
        changed = False
        for i, ch in enumerate(pattern):
            if ch != "(" or (i and pattern[i - 1] == "\\"):
                continue
            depth, j = 0, i
            while j < len(pattern):
                if pattern[j] == "\\":
                    j += 2
                    continue
                if pattern[j] == "(":
                    depth += 1
                elif pattern[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= len(pattern) or depth != 0:
                continue
            inner = pattern[i + 1:j]
            for prefix in ("?:", "?<", "?=", "?!"):
                if inner.startswith(prefix):
                    if prefix == "?<" and ">" in inner:
                        inner = inner[inner.index(">") + 1:]
                    elif prefix == "?:":
                        inner = inner[2:]
                    break
            candidate = pattern[:i] + inner + pattern[j + 1:]
            if candidate != pattern and oracle.interesting((api, candidate, flags, string)):
                pattern = candidate
                changed = True
                break
    return (api, pattern, flags, string)


def reduce_flags(case, oracle: Oracle):
    api, pattern, flags, string = case
    kept = ddmin(list(flags),
                 lambda sub: oracle.interesting((api, pattern, "".join(sorted(sub)), string)))
    return (api, pattern, "".join(sorted(kept)), string)


def simplify_api(case, oracle: Oracle):
    """Move to the most report-friendly API that still shows the same partition."""
    api, pattern, flags, string = case
    for candidate in API_PREFERENCE:
        if candidate == api:
            return case
        if oracle.interesting((candidate, pattern, flags, string)):
            return (candidate, pattern, flags, string)
    return case


def normalize_chars(case, oracle: Oracle):
    """Cosmetic final pass: try replacing each input char with 'a' / each literal too.

    A repro reading `.exec("aa")` is worth more in a bug report than one reading
    `.exec("#w?\x1dbvO_,9\x1cp")`, and costs a handful of runs.
    """
    api, pattern, flags, string = case
    for filler in ("a", "0"):
        for i in range(len(string)):
            if string[i] == filler:
                continue
            candidate = string[:i] + filler + string[i + 1:]
            if oracle.interesting((api, pattern, flags, candidate)):
                string = candidate
    return (api, pattern, flags, string)


PASSES = (
    ("api", simplify_api),
    ("flags", reduce_flags),
    ("groups", unwrap_groups),
    ("pattern", reduce_pattern_tokens),
    ("class", reduce_class_members),
    ("input", reduce_input),
)


def reduce_case(case, oracle: Oracle, rounds: int = 3, verbose: bool = False):
    """Run every pass to a fixpoint (or `rounds` sweeps, whichever comes first)."""
    for r in range(rounds):
        before = case
        for name, fn in PASSES:
            try:
                case = fn(case, oracle)
            except BudgetExhausted:
                if verbose:
                    print(f"  [budget exhausted during {name}]", file=sys.stderr)
                return case
            if verbose:
                print(f"  round {r} {name:8} -> api={case[0]} /{case[1]}/{case[2]} "
                      f"input={case[3]!r}", file=sys.stderr)
        if case == before:
            break
    return case


# --- Reporting ---------------------------------------------------------------

def diverging_keys(obs: dict) -> list[str]:
    """Which top-level keys of `value` actually differ across engines.

    The harness does not emit one result per case -- for a `g`/`y` regex it emits the
    whole lastIndex PRESET BATTERY, and `replace`/`split` emit a token/limit battery. So
    "the engines disagree" is usually true of only one entry in a dict of ten. Naming that
    entry is what turns a cluster into a repro someone can paste.
    """
    vals: dict[str, object] = {}
    for engine, comparable in obs.items():
        if comparable is None:
            continue
        try:
            vals[engine] = json.loads(comparable).get("value")
        except (json.JSONDecodeError, AttributeError):
            return []
    if len(vals) < 2 or not all(isinstance(v, dict) for v in vals.values()):
        return []
    keys: set[str] = set()
    for v in vals.values():
        keys.update(v.keys())            # type: ignore[union-attr]
    out = []
    for k in sorted(keys):
        rendered = {json.dumps(v.get(k), sort_keys=True)      # type: ignore[union-attr]
                    for v in vals.values()}
        if len(rendered) > 1:
            out.append(k)
    return out


def _preset_of(keys: list[str]) -> int | None:
    """The lastIndex of the first diverging `preset_<k>` entry, if any."""
    for k in keys:
        if k.startswith("preset_"):
            try:
                return int(k.split("_", 1)[1])
            except ValueError:
                continue
    return None


def repro_js(case, keys: list[str] | None = None) -> str:
    """A paste-able reproducer.

    MUST account for the preset battery: a reduced case whose divergence lives at
    `preset_1` does NOT reproduce from a bare `re.exec(s)`, because that runs at
    lastIndex 0. Emitting the bare form there would be an actively misleading artifact.
    """
    api, pattern, flags, string = case
    re_lit = f"new RegExp({json.dumps(pattern)}, {json.dumps(flags)})"
    s = json.dumps(string)
    preset = _preset_of(keys or [])

    if preset is not None:
        call = {
            "exec": f"re.exec({s})",
            "test": f"re.test({s})",
            "match": f"{s}.match(re)",
            "matchAll": f"[...{s}.matchAll(re)]",
            "search": f"{s}.search(re)",
        }.get(api, f"re.exec({s})")
        return (f"const re = {re_lit};\n"
                f"re.lastIndex = {preset};   // divergence is at this lastIndex, not 0\n"
                f"{call}")

    if api in ("exec", "test"):
        return f"{re_lit}.{api}({s})"
    if api in ("match", "matchAll", "search", "split"):
        return f"{s}.{api}({re_lit})"
    return f"{s}.{api}({re_lit}, \"$&\")"


def dedup_key(case, sig) -> str:
    """Exact-repro identity: same api + reduced pattern + flags + engine partition.

    Excludes the input (the witness, not the mechanism). This is the STRICT key -- use it
    when you want "these are literally the same reproducer".
    """
    api, pattern, flags, _ = case
    raw = json.dumps([api, pattern, flags, sig], sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def mechanism_key(case, sig, keys: list[str]) -> str:
    """Coarser identity: WHAT the engines disagreed about, ignoring which pattern showed it.

    Measured need: the four `matchAll`+`gv` witnesses of the surrogate `lastIndex` bug
    reduce to four DIFFERENT 1-minimal patterns (`[^;]`, `|`, `[^.]`, `.`) because any
    pattern that can match an astral code point witnesses it. They are one bug, so a key
    that includes the pattern still reports four. Dropping the pattern -- keeping api,
    flags, partition, and the diverging battery entry -- collapses them to one.

    This CAN over-merge (two unrelated bugs both surfacing at `preset_1` with the same
    partition), which is why both keys are emitted and neither is authoritative. Cluster
    on this, then read the reduced patterns within a cluster to confirm.
    """
    api, _pattern, flags, _ = case
    raw = json.dumps([api, flags, sig, sorted(keys)], sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def reduce_one(case, engines, timeout, budget_limit, verbose=False) -> dict:
    budget = Budget(budget_limit)
    observer = Observer(engines, timeout, budget)
    obs0 = observer.observe(case)
    if not is_discrepancy(obs0):
        return {"ok": False, "reason": "case does not reproduce a value discrepancy",
                "original": _case_json(case)}
    target = signature(obs0)
    oracle = Oracle(observer, target)
    reduced = reduce_case(case, oracle, verbose=verbose)
    keys = diverging_keys(observer.observe(reduced))
    return {
        "ok": True,
        "original": _case_json(case),
        "reduced": _case_json(reduced),
        "signature": [list(g) for g in target],
        "diverging_keys": keys,
        "repro_js": repro_js(reduced, keys),
        "dedup_key": dedup_key(reduced, target),
        "mechanism_key": mechanism_key(reduced, target, keys),
        "engine_runs": budget.used,
        "shrink": {
            "pattern": [len(case[1]), len(reduced[1])],
            "input": [len(case[3]), len(reduced[3])],
        },
    }


def _case_json(case) -> dict:
    api, pattern, flags, string = case
    return {"api": api, "pattern": pattern, "flags": flags, "input": string}


# --- Input adapters ----------------------------------------------------------

def case_from_diff(path: str, n: int | None, flags: str | None):
    """Pull a discrepancy case out of a stored `<api>.diff.json`."""
    with open(path) as fh:
        d = json.load(fh)
    for r in d["results"]:
        if not r.get("value_discrepancy"):
            continue
        if n is not None and r["n"] != n:
            continue
        if flags is not None and r["flags"] != flags:
            continue
        strings = _strings_for(path, d, r["n"])
        return (d["api"], d["pattern"], r["flags"], strings)
    raise SystemExit(f"no matching discrepancy in {path}")


def _strings_for(diff_path: str, d: dict, n: int) -> str:
    """The nth generated input for this (regex, api), from the sibling strings.jsonl."""
    base = os.path.dirname(diff_path)
    spath = os.path.join(base, f"{d['api']}.strings.jsonl")
    if not os.path.exists(spath):
        raise SystemExit(f"cannot find inputs at {spath} -- pass --input explicitly")
    with open(spath, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    body = [r for r in rows if "string" in r]
    if n >= len(body):
        raise SystemExit(f"n={n} out of range ({len(body)} strings)")
    return body[n]["string"]


def batch_headline(headline_path: str, results_root: str, engines, timeout: float,
                   budget_limit: int, limit: int | None, verbose: bool) -> dict:
    """Reduce one representative per (regex, api, flags) group, then cluster.

    Reducing every CELL would be wasteful and slow: a headline's 3772 discrepancies are
    ~46 clusters, and cells within a cluster reduce to the same thing by construction. So
    pick representatives cheaply (no engine runs), reduce those, and cluster the RESULTS
    by mechanism -- which is the step `dedupe_headline.py` cannot do, because it only ever
    sees the original corpus patterns.
    """
    with open(headline_path) as fh:
        headline = json.load(fh)

    # Representatives are taken ROUND-ROBIN across regexes, not in headline order.
    # The headline lists discrepancies grouped by regex, so a depth-first `--limit 40`
    # spends the entire budget inside the first regex or two and reports a mechanism
    # count for a window it never looked at. Round-robin makes any --limit a spread
    # sample: one per regex, then a second per regex, and so on.
    seen: set[tuple] = set()
    by_regex: dict[str, list] = {}
    for d in headline.get("discrepancies", []):
        key = (d["regex_id"], d["api"], d["flags"])
        if key in seen:
            continue
        seen.add(key)
        by_regex.setdefault(d["regex_id"], []).append((key, d))

    ordered = []
    depth = 0
    while True:
        added = False
        for rid in by_regex:
            if depth < len(by_regex[rid]):
                ordered.append(by_regex[rid][depth])
                added = True
        if not added:
            break
        depth += 1
    if limit is not None:
        ordered = ordered[:limit]

    results, failures = [], []
    for i, ((rid, api, flags), d) in enumerate(ordered, 1):
        diff_path = os.path.join(results_root, rid, f"{api}.diff.json")
        if not os.path.exists(diff_path):
            failures.append({"regex_id": rid, "api": api, "flags": flags,
                             "reason": "diff artifact missing"})
            continue
        try:
            case = case_from_diff(diff_path, d["n"], flags)
            out = reduce_one(case, engines, timeout, budget_limit, verbose=False)
        except SystemExit as e:
            failures.append({"regex_id": rid, "api": api, "flags": flags, "reason": str(e)})
            continue
        except Exception as e:                       # noqa: BLE001 -- one bad case must
            failures.append({"regex_id": rid, "api": api,   # not abort a batch of hundreds
                             "flags": flags, "reason": f"{type(e).__name__}: {e}"})
            continue
        if not out.get("ok"):
            failures.append({"regex_id": rid, "api": api, "flags": flags,
                             "reason": out.get("reason", "did not reproduce")})
            continue
        out["regex_id"] = rid
        results.append(out)
        if verbose:
            print(f"[{i}/{len(ordered)}] {rid} {api} /{flags}/ -> "
                  f"/{out['reduced']['pattern']}/{out['reduced']['flags']} "
                  f"[{out['mechanism_key']}]", file=sys.stderr)

    clusters: dict[str, list] = {}
    for r in results:
        clusters.setdefault(r["mechanism_key"], []).append(r)

    summary = []
    for mkey, members in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
        summary.append({
            "mechanism_key": mkey,
            "witnesses": len(members),
            "regexes": sorted({m["regex_id"] for m in members}),
            "signature": members[0]["signature"],
            "diverging_keys": members[0]["diverging_keys"],
            "distinct_reduced_patterns": sorted({m["reduced"]["pattern"] for m in members}),
            "example_repro": members[0]["repro_js"],
        })

    return {
        "headline": os.path.basename(headline_path),
        "window": headline.get("window"),
        "raw_discrepancies": len(headline.get("discrepancies", [])),
        "representatives_attempted": len(ordered),
        "reduced_ok": len(results),
        "failed": failures,
        "distinct_mechanisms": len(clusters),
        "clusters": summary,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", choices=sorted(DESCRIPTORS_BY_API))
    ap.add_argument("--pattern")
    ap.add_argument("--flags", default=None)
    ap.add_argument("--input")
    ap.add_argument("--from-diff", help="a results/<rid>/<api>.diff.json")
    ap.add_argument("--headline", help="reduce+cluster a whole eval_headline_<w>.json")
    ap.add_argument("--results-root", default="results",
                    help="where the per-regex artifact dirs live (batch mode)")
    ap.add_argument("--limit", type=int, default=None,
                    help="batch mode: only this many (regex, api, flags) representatives")
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--engines", default=",".join(DEFAULT_ENGINES))
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--budget", type=int, default=4000, help="max engine invocations")
    ap.add_argument("--out")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    engines = tuple(e.strip() for e in args.engines.split(",") if e.strip())

    if args.headline:
        result = batch_headline(args.headline, args.results_root, engines, args.timeout,
                                args.budget, args.limit, args.verbose)
    elif args.from_diff:
        case = case_from_diff(args.from_diff, args.n, args.flags)
        result = reduce_one(case, engines, args.timeout, args.budget, verbose=args.verbose)
    elif args.pattern is not None and args.input is not None and args.api:
        case = (args.api, args.pattern, args.flags or "", args.input)
        result = reduce_one(case, engines, args.timeout, args.budget, verbose=args.verbose)
    else:
        ap.error("give --api/--pattern/--input, or --from-diff, or --headline")
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
