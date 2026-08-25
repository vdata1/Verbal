"""Offline check: run the REAL classify() from nominate_probe over the cached curves
(targets + controls) and the recorded 7984 hang, and assert each lands where intended."""
import importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Import classify() without running nominate_probe's __main__ corpus sweep: load the
# module source up to (not including) the argparse block. Simplest: exec with a guard.
src = open(os.path.join(HERE, "nominate_probe.py")).read()
src = src.split("ap = argparse.ArgumentParser()")[0]
# strip the chaos import (needs the pipeline pkg / not required for classify)
src = src.replace("from pipeline.chaos import mutants, rng_for  # noqa: E402", "")
ns = {"__file__": os.path.join(HERE, "nominate_probe.py")}
exec(compile(src, "nominate_probe.py", "exec"), ns)
classify = ns["classify"]

d = json.load(open(os.path.join(HERE, "dev_curves.json")))

# The recorded 7984 hang from the new harness (captured live earlier).
HANG_7984 = json.load(open("/tmp/h7984.json")) if os.path.exists("/tmp/h7984.json") else \
    {"ok": True, "hung": True, "hung_len": 52, "points": [], "baseline_ms": 4e-5}

# 6580/9577 must be EXPONENTIAL, 7984 HANG. The two ex-false-positives (8206, 8848)
# must simply NOT be EXPONENTIAL anymore -- where they land (UNCLASSIFIED/POLYNOMIAL) is
# the untriaged bucket, not a false promotion.
EXPECT = {
    "regex_6580": "EXPONENTIAL", "regex_9577": "EXPONENTIAL", "regex_7984": "HANG",
    "regex_8206": "not EXPONENTIAL", "regex_8848": "not EXPONENTIAL",
}

print("=== TARGETS ===")
allok = True
for rid, want in EXPECT.items():
    res = HANG_7984 if rid == "regex_7984" else d[rid]
    v, detail = classify(res)
    ok = (v != "EXPONENTIAL") if want == "not EXPONENTIAL" else (v == want)
    allok &= ok
    print(f"  {'PASS' if ok else 'FAIL'}  {rid:<12} -> {v:<12} (want {want})")
    print(f"        {detail}")

print("=== CONTROLS ===")
for name, r in d["__controls__"].items():
    want = r["expect"]
    v, detail = classify(r)
    ok = (v == want)
    allok &= ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<32} -> {v:<12} (want {want})")
    print(f"        {detail}")

print("\n" + ("ALL PASS" if allok else "!!! SOME FAILED"))
sys.exit(0 if allok else 1)
