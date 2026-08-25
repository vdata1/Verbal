#!/usr/bin/env python3
"""Collapse an eval headline's per-cell discrepancy list into root causes.

The headline counts one discrepancy per (regex, string, flag set, API) cell, so a
single engine-level fact is booked hundreds of times: `regex_11383` fails to COMPILE
under `v` in bun -- one syntax fact -- and that alone books 480 discrepancies across
8 APIs x 60 strings. Window 11050-12050 reported 4031 discrepancies from 20 regexes
and ~5 real causes; window 10050-11050 reported 1652, of which 1560 (94%) were
re-finds of F001 (deno's `\\p{...}` tables lagging Unicode 17, already filed).

Raw counts are left untouched -- this reports the deduped view ALONGSIDE them, so
nothing about the recorded run changes. A cluster is keyed by

    (regex_id, kind, engine partition)

where `kind` separates a compile-time divergence from a value divergence: those are
different bugs even in the same regex, and `regex_11692` is exactly that case (bun is
the outlier on exec/match/matchAll/test, deno on replace/replaceAll/search/split).

Usage:
    python3 analysis/eval_help_scripts/dedupe_headline.py <eval_headline.json> \\
        [--redos <redos.json>] [--json]
"""
import argparse
import collections
import json
import os
import sys

# --- Known causes -------------------------------------------------------------
# A cluster matching one of these is a re-find, not new signal. Keeping them named
# here (rather than filtering them out) means a re-find still shows up in the report
# -- it is evidence the bug is still live -- it just does not compete with new work.
F001 = "F001 deno \\p{...} tables lag Unicode 17 (filed)"
BUN_CAP = "bun backtrack cap / unsound step limit (known)"


def _load(path):
    with open(path) as fh:
        return json.load(fh)


def _partition(runs):
    """Engines grouped by identical comparable output: (('bun',), ('deno','node'))."""
    groups = collections.defaultdict(list)
    for eng, r in runs.items():
        groups[r.get("comparable")].append(eng)
    return tuple(sorted(tuple(sorted(v)) for v in groups.values()))


def _outlier(partition):
    """The lone engine when the split is 1-vs-rest, else None."""
    singles = [g for g in partition if len(g) == 1]
    if len(partition) == 2 and len(singles) == 1:
        return singles[0][0]
    return None


def _kind(runs):
    """`syntax` when at least one engine refused to compile, else `value`."""
    for r in runs.values():
        c = r.get("comparable")
        if c and '"ok": false' in c and "SyntaxError" in c:
            return "syntax"
    return "value"


def _classify(pattern, kind, partition):
    """Name a known root cause for this cluster, or None if it looks new."""
    out = _outlier(partition)
    if out == "deno" and kind == "value" and ("\\p{" in pattern or "\\P{" in pattern):
        return F001
    return None


def collect(headline_path):
    """Walk the headline's discrepancy pointers into their per-API diff artifacts."""
    head = _load(headline_path)
    results_dir = os.path.dirname(os.path.abspath(headline_path))
    raw = head.get("discrepancies", [])

    # One diff.json holds every case for a (regex, api); read each at most once.
    seen_files, clusters, unreadable = {}, collections.defaultdict(lambda: {
        "cases": 0, "apis": set(), "flags": set(), "pattern": ""}), 0
    for d in raw:
        rid, api = d["regex_id"], d["api"]
        key = (rid, api)
        if key not in seen_files:
            p = os.path.join(results_dir, rid, f"{api}.diff.json")
            try:
                seen_files[key] = _load(p)
            except (OSError, ValueError):
                seen_files[key] = None
        art = seen_files[key]
        if art is None:
            unreadable += 1
            continue
        # Match the headline pointer to its case by (n, flags).
        for c in art["results"]:
            if c["n"] == d["n"] and c["flags"] == d["flags"] and c.get("value_discrepancy"):
                part = _partition(c["runs"])
                ck = (rid, _kind(c["runs"]), part)
                e = clusters[ck]
                e["cases"] += 1
                e["apis"].add(api)
                e["flags"].add(d["flags"])
                e["pattern"] = art["pattern"]
                break

    return head, raw, clusters, unreadable


def redos_clusters(redos_path):
    """Group confirmed ReDoS entries, separating bun's step-limit bailouts."""
    d = _load(redos_path)
    conf = d.get("confirmed", [])
    by = collections.defaultdict(lambda: {"cases": 0, "es": 0, "pattern": "",
                                          "apis": set()})
    for c in conf:
        e = by[c["regex_id"]]
        e["cases"] += 1
        e["pattern"] = c.get("pattern", "")
        e["apis"].add(c.get("api"))
        # `engine_specific` with bun fastest is the known cap, not a differential.
        if c.get("engine_specific"):
            e["es"] += 1
            e.setdefault("bun_fastest", 0)
            if c.get("fastest_engine") == "bun":
                e["bun_fastest"] += 1
    return d, by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("headline")
    ap.add_argument("--redos")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    head, raw, clusters, unreadable = collect(a.headline)
    w = head.get("window", {})

    rows = []
    for (rid, kind, part), e in clusters.items():
        rows.append({
            "regex_id": rid,
            "kind": kind,
            "partition": " | ".join("+".join(g) for g in part),
            "outlier": _outlier(part),
            "cases": e["cases"],
            "apis": sorted(e["apis"]),
            "flags": sorted(e["flags"]),
            "pattern": e["pattern"],
            "known_cause": _classify(e["pattern"], kind, part),
        })
    rows.sort(key=lambda r: -r["cases"])

    new = [r for r in rows if not r["known_cause"]]
    known = [r for r in rows if r["known_cause"]]
    known_cases = sum(r["cases"] for r in known)

    if a.json:
        print(json.dumps({"window": w, "raw_discrepancies": len(raw),
                          "clusters": rows}, indent=2))
        return

    print(f"window {w.get('start')}-{w.get('end')}   "
          f"raw discrepancies: {len(raw)}   "
          f"distinct regexes: {len({d['regex_id'] for d in raw})}   "
          f"ROOT-CAUSE CLUSTERS: {len(rows)}")
    if len(raw):
        print(f"  amplification: {len(raw) / max(len(rows), 1):.0f}x   "
              f"known-cause share: {known_cases}/{len(raw)} "
              f"({100.0 * known_cases / len(raw):.0f}%)")
    if unreadable:
        print(f"  [warn] {unreadable} pointers had no readable diff artifact")

    # --- Cross-regex signatures ----------------------------------------------
    # Per-regex clustering still over-splits: window 10050-11050 ends with a dozen
    # one-case clusters that are all matchAll + `gv` + bun-as-outlier, i.e. almost
    # certainly ONE bun v-mode bug seen through a dozen unrelated patterns. Two
    # clusters share a signature when the divergence kind, the engine partition, the
    # APIs and the flags all agree -- what differs is only which pattern tripped it.
    sigs = collections.defaultdict(list)
    for r in rows:
        sigs[(r["kind"], r["partition"], tuple(r["apis"]), tuple(r["flags"]))].append(r)
    shared = sorted((v for v in sigs.values() if len(v) >= 3),
                    key=lambda v: -sum(x["cases"] for x in v))
    if shared:
        print(f"\n--- SHARED SIGNATURES ({len(shared)}; >=3 regexes each) ---")
        print("    same kind+partition+apis+flags across unrelated patterns "
              "-> likely one engine bug, not N")
        for grp in shared:
            g = grp[0]
            print(f"  {g['kind']:6s} {g['partition']:20s} "
                  f"apis={','.join(g['apis'])} flags={','.join(x or '(none)' for x in g['flags'])}")
            print(f"    {len(grp)} regexes, {sum(x['cases'] for x in grp)} cases: "
                  f"{', '.join(x['regex_id'] for x in grp[:8])}"
                  f"{' ...' if len(grp) > 8 else ''}")

    for label, group in (("NEW", new), ("KNOWN", known)):
        if not group:
            continue
        print(f"\n--- {label} ({len(group)} clusters) ---")
        for r in group:
            tag = f"  [{r['known_cause']}]" if r["known_cause"] else ""
            print(f"{r['regex_id']:16s} {r['kind']:6s} {r['cases']:5d} cases  "
                  f"{r['partition']}{tag}")
            print(f"    pattern: {r['pattern'][:96]}")
            print(f"    apis: {','.join(r['apis'])}   flags: {','.join(x or '(none)' for x in r['flags'])}")

    if a.redos:
        d, by = redos_clusters(a.redos)
        print(f"\n=== ReDoS: {d.get('confirmed') and len(d['confirmed'])} confirmed entries "
              f"-> {len(by)} distinct regexes ===")
        for rid, e in sorted(by.items(), key=lambda kv: -kv[1]["cases"]):
            cap = e.get("bun_fastest", 0)
            note = ""
            if e["es"]:
                note = (f"   engine_specific={e['es']}"
                        f" (bun fastest in {cap} -> {BUN_CAP})" if cap else
                        f"   engine_specific={e['es']}")
            print(f"{rid:16s} {e['cases']:5d} entries{note}")
            print(f"    pattern: {e['pattern'][:96]}")


if __name__ == "__main__":
    sys.exit(main())
