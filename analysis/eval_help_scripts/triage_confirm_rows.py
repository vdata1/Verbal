"""Static triage of the 2026-08-07 confirm outputs. No engine execution."""
import json, collections, statistics, re, sys

RESULTS = "/scratch/turcotte/verbal/results"
FILES = ["redos_12050_15050.json", "redos_15050_20035.json"]

rows, verdicts = [], []
meta = {}
for f in FILES:
    d = json.load(open(f"{RESULTS}/{f}"))
    meta[f] = {k: d[k] for k in ("candidates", "confirmed", "load_artifacts",
                                 "unmeasured", "slow_ms", "engine_ratio",
                                 "harness_timeout_s", "confirm_elapsed_s")
               if k in d}
    meta[f]["confirmed"] = len(d["confirmed"])
    meta[f]["window"] = d["window"]
    for r in d["confirmed"]:
        rows.append(dict(r, _src=f))
    for v in d["verdicts"]:
        verdicts.append(dict(v, _src=f))

BUDGET = 20000.0

def censored(r):
    """Which engines are scored at the budget rather than measured."""
    return set(r.get("timed_out") or [])

per = collections.defaultdict(list)
for r in rows:
    per[r["regex_id"]].append(r)

print("=" * 100)
print("QUEUE-LEVEL")
for f, m in meta.items():
    print(f"  {f}: window {m['window']}  candidates {m['candidates']}  "
          f"confirmed {m['confirmed']}  load_artifacts {m['load_artifacts']}  "
          f"unmeasured {m['unmeasured']}  elapsed {m['confirm_elapsed_s']}s")
print(f"  gates: slow_ms={meta[FILES[0]]['slow_ms']} "
      f"engine_ratio={meta[FILES[0]]['engine_ratio']} budget={BUDGET}ms")

print("\n" + "=" * 100)
print("PER-REGEX")
summary = {}
for rid, rs in sorted(per.items(), key=lambda kv: -len(kv[1])):
    es = [r for r in rs if r["engine_specific"]]
    # Strongest evidence: engine-specific AND nothing censored -> a real two-sided reading
    clean_es = [r for r in es if not censored(r)]
    # engine-specific but the slow side is censored -> ratio is a sound LOWER bound
    lb_es = [r for r in es if censored(r)]
    # rows where every engine hit the wall -> ratio 1.0, no information
    allto = [r for r in rs if len(censored(r)) >= 3]
    slow = collections.Counter(r["slowest_engine"] for r in rs)
    fast = collections.Counter(r["fastest_engine"] for r in rs)
    slow_es = collections.Counter(r["slowest_engine"] for r in es)
    ratios = sorted(r["ratio"] for r in es if r["ratio"] is not None)
    apis = collections.Counter(r["api"] for r in rs)
    flags = collections.Counter(r["flags"] or "none" for r in rs)
    ns = sorted({r["n"] for r in rs})
    summary[rid] = dict(rows=len(rs), es=len(es), clean_es=len(clean_es),
                        lb_es=len(lb_es), allto=len(allto))
    print(f"\n--- {rid}  ({len(rs)} confirmed rows, {len(es)} engine-specific) ---")
    print(f"  pattern : {rs[0]['pattern']!r}")
    print(f"  slowest : {dict(slow)}   (among engine-specific: {dict(slow_es)})")
    print(f"  fastest : {dict(fast)}")
    print(f"  apis    : {dict(apis)}")
    print(f"  flags   : {dict(flags)}")
    print(f"  distinct input indices n: {len(ns)} {ns[:12]}{'...' if len(ns) > 12 else ''}")
    print(f"  engine-specific evidence quality:")
    print(f"      fully measured (no timeout, ratio is a real number) : {len(clean_es)}")
    print(f"      slow side censored at budget (ratio = LOWER bound)  : {len(lb_es)}")
    print(f"  all-three-timed-out rows (ratio 1.0, no signal)         : {len(allto)}")
    if ratios:
        print(f"  ratio among engine-specific: min {ratios[0]:.1f} "
              f"median {statistics.median(ratios):.1f} max {ratios[-1]:.1f}")
    if clean_es:
        ex = sorted(clean_es, key=lambda r: -(r["ratio"] or 0))[:3]
        print("  strongest fully-measured rows:")
        for r in ex:
            print(f"      {r['api']} #{r['n']} [{r['flags'] or 'none'}] "
                  f"{r['slowest_engine']}={r['serial_ms'][r['slowest_engine']]:.0f}ms "
                  f"{r['fastest_engine']}={r['serial_ms'][r['fastest_engine']]:.0f}ms "
                  f"ratio {r['ratio']:.1f}")

print("\n" + "=" * 100)
print("TOTALS")
tot = lambda k: sum(v[k] for v in summary.values())
print(f"  confirmed rows           : {tot('rows')}")
print(f"  engine-specific rows     : {tot('es')}")
print(f"    fully measured         : {tot('clean_es')}")
print(f"    lower-bound only       : {tot('lb_es')}")
print(f"  all-3-timeout rows       : {tot('allto')}")
print(f"  distinct regexes         : {len(summary)}")
