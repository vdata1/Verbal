"""Did the agreed-upon value actually contain a MATCH, or is it a no-match?

Why this matters: bun's known unsound step cap (analysis/bug_reports/
REPORT_bun_backtracking_step_cap.md) bails out of a long backtrack and reports NO MATCH.
When the true answer is also no-match, bun is right by accident and 20x faster. Such a row
is the step cap being observed from the timing side -- not bun outperforming V8.

Per-API unwrapping, including the lastIndex-preset dicts (`preset_0`, `preset_1`, ...) and
the replace-template dicts (`[$$]`, `[$&]`, ...).
"""
import json, os, collections

RESULTS = "/scratch/turcotte/verbal/results"
rows = []
for f in ("redos_12050_15050.json", "redos_15050_20035.json"):
    rows += json.load(open(f"{RESULTS}/{f}"))["confirmed"]

cache = {}
def lookup(rid, api, n, flags):
    key = (rid, api)
    if key not in cache:
        p = f"{RESULTS}/{rid}/{api}.diff.json"
        cache[key] = ({(e["n"], e["flags"]): e for e in json.load(open(p))["results"]}
                      if os.path.exists(p) else None)
    return None if cache[key] is None else cache[key].get((n, flags))


def leaf_matched(api, v):
    """True iff this leaf value represents a SUCCESSFUL match."""
    if api == "test":                       return v is True
    if api == "search":                     return isinstance(v, int) and v >= 0
    if api in ("exec", "match"):            return v is not None
    if api == "matchAll":                   return isinstance(v, list) and len(v) > 0
    if api == "split":
        # a split that yields >1 piece means the separator matched at least once
        return isinstance(v, list) and len(v) > 1
    return None


def matched(api, val):
    """Unwrap preset / template dicts; True if ANY variant shows a match."""
    if api in ("replace", "replaceAll"):
        # val is {template: output}. With no match every template returns the input
        # verbatim, so all outputs are identical. Distinct outputs => a match occurred.
        if isinstance(val, dict):
            outs = set()
            for v in val.values():
                outs.add(json.dumps(v, sort_keys=True) if not isinstance(v, str) else v)
            return len(outs) > 1
        return None
    if isinstance(val, dict):
        # preset dict: {preset_k: {lastIndex: i, result: <leaf>}}
        seen = []
        for v in val.values():
            if isinstance(v, dict) and "result" in v:
                seen.append(leaf_matched(api, v["result"]))
            else:
                seen.append(leaf_matched(api, v))
        seen = [s for s in seen if s is not None]
        return any(seen) if seen else None
    return leaf_matched(api, val)


def classify(api, entry):
    if entry is None:                    return "no_record"
    if entry.get("any_timeout"):         return "V8_TIMED_OUT_no_value"
    vals = entry.get("distinct_values") or []
    if len(vals) > 1:                    return "VALUE_DISCREPANCY"
    if not vals:                         return "no_value"
    m = matched(api, json.loads(vals[0]).get("value"))
    if m is None:                        return "unclassified"
    return "MATCH_FOUND" if m else "agreed_NO_MATCH"


per = collections.defaultdict(collections.Counter)
per_es = collections.defaultdict(collections.Counter)
examples = collections.defaultdict(list)
for r in rows:
    e = lookup(r["regex_id"], r["api"], r["n"], r["flags"])
    c = classify(r["api"], e)
    per[r["regex_id"]][c] += 1
    if r["engine_specific"]:
        per_es[r["regex_id"]][c] += 1
        if c == "MATCH_FOUND":
            examples[r["regex_id"]].append(r)

W = 62
print(f'{"regex":<14}  {"ALL confirmed":<{W}}engine-specific')
for rid in sorted(per, key=lambda k: -sum(per[k].values())):
    print(f"{rid:<14}  {str(dict(per[rid])):<{W}}{dict(per_es[rid])}")

tot, tot_es = collections.Counter(), collections.Counter()
for rid in per:
    tot += per[rid]; tot_es += per_es[rid]
print("\n=== TOTAL ===")
print(" all 848 confirmed :", dict(tot))
print(" 477 engine-specific:", dict(tot_es))

print("\n=== engine-specific rows with a REAL match (bun fast AND correct on a match) ===")
for rid, rs in examples.items():
    for r in rs:
        ms = r["serial_ms"]
        print(f'  {rid} {r["api"]} #{r["n"]} [{r["flags"] or "none"}] '
              f'{r["slowest_engine"]}={ms[r["slowest_engine"]]:.0f}ms '
              f'{r["fastest_engine"]}={ms[r["fastest_engine"]]:.0f}ms ratio={r["ratio"]:.0f}')
