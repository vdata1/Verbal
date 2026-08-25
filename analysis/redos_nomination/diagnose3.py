"""For the 3 oracle-wedgers: is it mid_delete destroying the pump, or is node just not
pathological where Python is? Show the chosen seed, then time its mid_delete ladder on
BOTH python-re (bounded) and node."""
import glob, json, os, re, signal, subprocess, sys, time
sys.path.insert(0,"/repo/src")
from pipeline.chaos import mutants, rng_for
OPS=("delete","insert","substitute","duplicate","transpose","case_flip","truncate")
ALPHA=tuple("abcXYZ019 _-.!@#/\\\t\n"); SEED=20260716
HARNESS="/probe/ladder_harness.js"; SPEC="/tmp/d3.json"
class TO(Exception): pass
signal.signal(signal.SIGALRM, lambda s,f:(_ for _ in ()).throw(TO()))
def py_ms(rx,s,ms=1000):
    signal.setitimer(signal.ITIMER_REAL,ms/1000)
    t=time.perf_counter()
    try: rx.search(s); return (time.perf_counter()-t)*1000, False
    except TO: return ms, True
    finally: signal.setitimer(signal.ITIMER_REAL,0)
def mid(s,L): a,b=(L+1)//2,L//2; return s[:a]+(s[len(s)-b:] if b else "")
def node_sweep(pat,fl,inputs):
    json.dump({"pattern":pat,"flags":fl,"inputs":inputs},open(SPEC,"w"))
    p=subprocess.run(["node",HARNESS,SPEC],capture_output=True,text=True,timeout=60)
    for l in p.stdout.split("\n"):
        try: o=json.loads(l.strip())
        except: continue
        if isinstance(o,dict) and "ok" in o: return o
    return {"ok":False}

TARGETS=["regex_6580","regex_9577"]
for rid in TARGETS:
    path=f"/repo/results-run-6000-9999/{rid}/test.strings.jsonl"
    meta=None;fuzz=[]
    for line in open(path):
        try:o=json.loads(line)
        except:continue
        if o.get("kind")=="meta":meta=o
        elif o.get("kind")=="string":fuzz.append(o["string"])
    rx=re.compile(meta["pattern"])
    seen=set(fuzz);cands=[]
    for i,s in enumerate(fuzz):
        for m,_ in mutants(s,2,rng_for(SEED,rid,"test",i),OPS,ALPHA,seen):
            seen.add(m)
            _,to=py_ms(rx,m,200)
            if to or not rx.search(m) if not to else True:
                cands.append((m,to))
    # priority: timed-out first, then longest (same rule as the probe)
    seed=max(cands,key=lambda mt:(mt[1],len(mt[0])))[0]
    print(f"\n{'='*70}\n{rid}: /{meta['pattern']}/")
    print(f"  seed ({len(seed)} chars): {seed!r}")
    Ls=sorted({max(1,int(1+i*len(seed)/24)) for i in range(24)}|{len(seed)})
    rungs=[mid(seed,L) for L in Ls]
    # python timing along the SAME ladder
    print("  python-re along mid_delete ladder:")
    prow=[]
    for L in Ls:
        ms,to=py_ms(rx,mid(seed,L),1000)
        prow.append(f"({L},{'TO' if to else f'{ms:.2f}ms'})")
    print("    "+" ".join(prow))
    r=node_sweep(meta["pattern"],meta.get("flags",""),rungs)
    if r.get("ok"):
        print("  node along same ladder:")
        print("    "+" ".join(f"({p['len']},{p['ms']*1000:.1f}us)" for p in r["points"]))
