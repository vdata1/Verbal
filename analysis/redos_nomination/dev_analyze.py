"""Offline: compute classify() internals + candidate discriminants on the cached
curves, so fix 1 (the exp/poly disambiguation) can be designed without re-running node."""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, "dev_curves.json")))


def ols(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    icept = my - slope * mx
    sst = sum((y - my) ** 2 for y in ys)
    ssr = sum((y - (icept + slope * x)) ** 2 for x, y in zip(xs, ys))
    return slope, icept, (1 - ssr / sst if sst > 0 else 1.0)


def analyze(name, r, expect):
    if not r.get("ok"):
        print(f"{name:<34} ok=False ({r.get('error')})  expect={expect}")
        return
    base, pts = r["baseline_ms"], r["points"]
    usable = [p for p in pts if p["ms"] >= 10 * base]
    dearest = usable[-1]["ms"] if usable else 0.0
    if len(usable) < 3:
        print(f"{name:<34} SAFE (<3 usable)  expect={expect}")
        return
    xs = [p["len"] for p in usable]
    ys = [math.log(p["ms"]) for p in usable]
    e = ols(xs, ys)
    q = ols([math.log(x) for x in xs], ys)
    b, k = math.exp(e[0]), q[0]

    # Candidate A: longest contiguous top-window whose exp-fit R2>=0.99 & base>=1.1.
    # Slide a window anchored at the dearest point, growing downward.
    bestwin = 0
    for i in range(len(usable) - 2):          # start index; window = usable[i:]
        wx, wy = xs[i:], ys[i:]
        ew = ols(wx, wy)
        if ew and ew[2] >= 0.99 and math.exp(ew[0]) >= 1.1:
            bestwin = len(wx)
            break                              # first (widest) qualifying suffix
    winfrac = bestwin / len(usable)

    # Candidate B: local per-unit-n log-slopes; exponential => ~constant, poly => decays.
    # Fit slope_i vs 1/n_i. Poly log t = k log n + c => d/dn = k/n (positive corr with 1/n).
    # Exp => slope ~ const (no corr). Report the fraction of downward drift.
    slopes, mids = [], []
    for i in range(len(usable) - 1):
        dn = xs[i + 1] - xs[i]
        if dn > 0:
            slopes.append((ys[i + 1] - ys[i]) / dn)
            mids.append((xs[i + 1] + xs[i]) / 2)
    # median slope over top half vs bottom half
    half = len(slopes) // 2
    lo = sorted(slopes[:half]) if half else []
    hi = sorted(slopes[half:])
    med = lambda a: a[len(a) // 2] if a else 0.0
    slope_lo, slope_hi = med(lo), med(hi)   # bottom-n vs top-n local slope

    print(f"{name:<34} expect={expect}")
    print(f"   usable={len(usable)}  dearest={dearest:.3f}ms  base={base*1e3:.4f}us")
    print(f"   EXP  base={b:.3f} R2={e[2]:.4f}    POLY k={k:.2f} R2={q[2]:.4f}"
          f"   (exp>poly? {e[2] > q[2]})")
    print(f"   [A] widest exp-clean suffix: {bestwin}/{len(usable)} pts (frac {winfrac:.2f})")
    print(f"   [B] local slope bottom-half med={slope_lo:.4f}  top-half med={slope_hi:.4f}"
          f"   (exp: ~equal; poly: top<bottom)")
    print()


print("=== TARGETS ===")
EXPECT = {"regex_6580": "EXPONENTIAL", "regex_9577": "EXPONENTIAL",
          "regex_7984": "HANG", "regex_8206": "SAFE", "regex_8848": "SAFE"}
for rid in ["regex_6580", "regex_9577", "regex_7984", "regex_8206", "regex_8848"]:
    analyze(rid, d[rid], EXPECT[rid])

print("=== CONTROLS ===")
for name, r in d["__controls__"].items():
    analyze(name, r, r["expect"])
