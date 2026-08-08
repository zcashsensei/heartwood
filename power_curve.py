"""Operating envelope of the Heartwood test at the MEASURED parameters.

Uses the empirically observed rates from gemma:2b -- honest 0.83, hollow 0.08
-- rather than assumed ones, so the power curve describes the real cliff.
"""
import numpy as np

import heartwood as H

rng = np.random.default_rng(20260808)

P_HONEST, P_HOLLOW = 0.725, 0.129   # measured in the live audits
P0, P1, ALPHA = 0.446, 0.30, 0.01   # p0 = Wilson 99% LCB on 23/36, as committed
LAM = H.kelly_lambda(P0, P1)
THR = np.log10(1.0 / ALPHA)

print(f"measured: honest={P_HONEST}  hollow={P_HOLLOW}")
print(f"plan:     p0={P0}  p1={P1}  alpha={ALPHA}  lambda*={LAM:.4f}  "
      f"threshold=log10(1/alpha)={THR:.0f}")
print()


def sim(p, n=20000, T=400):
    x = (rng.random((n, T)) < p).astype(float)
    inc = np.log10(1.0 + LAM * (P0 - x))
    lw = np.cumsum(inc, axis=1)
    hit = lw >= THR
    fired = hit.any(axis=1)
    first = np.where(fired, hit.argmax(axis=1) + 1, 0)
    q = first[fired]
    return fired.mean(), (np.median(q) if q.size else np.nan), \
        (np.percentile(q, 90) if q.size else np.nan)


print("FALSE POSITIVES (endpoint is honest or merely at the null boundary)")
for p, lbl in [(P0, "exactly at null boundary p0"),
               (0.70, "slightly above p0"),
               (P_HONEST, "true honest endpoint")]:
    r, m, _ = sim(p)
    print(f"  p={p:.3f} {lbl:28s} FPR={r:.4f}   (guarantee <= {ALPHA})")

print()
print("DETECTION (full downgrade)")
for p in [P_HOLLOW, 0.15, 0.25, 0.35, 0.45]:
    r, m, p90 = sim(p)
    print(f"  p={p:.2f}  detect={r:.3f}  median_queries={m:.0f}  p90={p90:.0f}")

print()
print("DILUTION SWEEP (fraction eps of traffic silently downgraded)")
print(f"  {'eps':>5} {'mixed p':>8} {'detect':>7} {'median q':>9} {'p90':>6}")
for eps in [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]:
    p = (1 - eps) * P_HONEST + eps * P_HOLLOW
    r, m, p90 = sim(p, n=6000, T=3000)
    print(f"  {eps:5.1f} {p:8.3f} {r:7.3f} {m:9.0f} {p90:6.0f}")

print()
print("COST OF THE GUARANTEE: queries needed vs confidence level")
for a in [0.05, 0.01, 0.001, 1e-6]:
    thr = np.log10(1 / a)
    per = 0.92 * np.log10(1 + LAM * P0) + 0.08 * np.log10(1 + LAM * (P0 - 1))
    print(f"  alpha={a:<8g} threshold=10^{thr:.0f}  "
          f"~{thr/per:.0f} queries at the measured hollow rate")
