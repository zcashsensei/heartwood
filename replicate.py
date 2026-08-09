"""Independent replications: turn one anecdote into a distribution.

A single audit that fires at query 31 is an anecdote. Running N independent
audits -- each with its own pool seed, so a different committed pool and a
different beacon-derived order -- gives a distribution of queries-to-detection
and an observed false-positive count. That is what a reviewer will ask for.
"""
import json
import pathlib
import statistics
import sys
import time

import run_audit as R

HERE = pathlib.Path(__file__).parent
P0, P1, ALPHA = 0.446, 0.30, 0.01
DIFF, FAMS = 0, ["state_track", "money_chain"]

n_hollow = int(sys.argv[1]) if len(sys.argv) > 1 else 5
n_honest = int(sys.argv[2]) if len(sys.argv) > 2 else 3

rows = []
for i in range(n_hollow):
    t0 = time.time()
    rec = R.audit(P0, P1, ALPHA, 900000 + i, 300, DIFF, "hollow",
                  max_q=120, families=FAMS, verbose=False)
    r = rec["result"]
    rows.append({"scenario": "hollow", "seed": 900000 + i,
                 "fired_at": r["rejected_at"], "n": r["n_queries"],
                 "rate": r["observed_rate"], "w": r["peak_log10_wealth"],
                 "secs": round(time.time() - t0)})
    print(f"hollow  seed={900000+i} fired_at={r['rejected_at']} "
          f"rate={r['observed_rate']:.3f} log10W={r['peak_log10_wealth']:+.2f} "
          f"({rows[-1]['secs']}s)", flush=True)

for i in range(n_honest):
    t0 = time.time()
    rec = R.audit(P0, P1, ALPHA, 800000 + i, 300, DIFF, "honest",
                  max_q=45, families=FAMS, verbose=False)
    r = rec["result"]
    rows.append({"scenario": "honest", "seed": 800000 + i,
                 "fired_at": r["rejected_at"], "n": r["n_queries"],
                 "rate": r["observed_rate"], "w": r["peak_log10_wealth"],
                 "secs": round(time.time() - t0)})
    print(f"honest  seed={800000+i} fired_at={r['rejected_at']} "
          f"rate={r['observed_rate']:.3f} log10W={r['peak_log10_wealth']:+.2f} "
          f"({rows[-1]['secs']}s)", flush=True)

(HERE / "evidence" / "replications.json").write_text(json.dumps(rows, indent=1))

h = [r for r in rows if r["scenario"] == "hollow"]
o = [r for r in rows if r["scenario"] == "honest"]
fired = [r["fired_at"] for r in h if r["fired_at"]]
print()
print(f"HOLLOW  detected {len(fired)}/{len(h)}")
if fired:
    print(f"  queries-to-detection: min={min(fired)} median={statistics.median(fired):.0f} "
          f"max={max(fired)}")
fp = [r for r in o if r["fired_at"]]
print(f"HONEST  false positives {len(fp)}/{len(o)}   (alpha={ALPHA})")
print(f"  peak evidence: {[f'10^{r['w']:+.2f}' for r in o]}")
