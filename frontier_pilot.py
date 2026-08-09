"""Locate the capability cliff for a FRONTIER model.

Tiers 0-3 are calibrated to a 2B local model; a frontier model solves them
without spending real compute, so they carry no evidence there. This sweeps
the harder tiers to find where thinking-enabled succeeds and thinking-disabled
does not -- the band where each query is informative.
"""
import sys
import time

import challenges as C
import endpoint as E
import providers

n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
tiers = [int(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2
                          else ["3", "4", "5"])]
fams = ["state_track"]

model = sys.argv[3] if len(sys.argv) > 3 else "claude-haiku-4-5"
p = providers.get_provider("anthropic", model=model)
print(f"model={p.model} think_budget={p.think_budget} "
      f"honest_max={p.honest_max} hollow_max={p.hollow_max}")
print()

for d in tiers:
    pool = C.make_pool(555001, n, d, fams)
    out = {}
    for mode in ("honest", "hollow"):
        ok = tok = thk = 0
        t0 = time.time()
        for it in pool:
            try:
                txt, meta = p.query(it["q"], mode)
            except Exception as e:
                txt, meta = f"<ERR {type(e).__name__}>", {}
            ok += E.grade(E.extract(txt), it["a"], txt)
            tok += meta.get("output_tokens", 0)
            thk += meta.get("thinking_chars", 0)
        out[mode] = (ok / len(pool), tok / len(pool), thk / len(pool),
                     time.time() - t0)
    h, x = out["honest"], out["hollow"]
    print(f"diff{d}: honest={h[0]:.2f} (out_tok {h[1]:.0f}, think {h[2]:.0f} chars)  "
          f"hollow={x[0]:.2f} (out_tok {x[1]:.0f}, think {x[2]:.0f})  "
          f"sep={h[0]-x[0]:+.2f}", flush=True)
