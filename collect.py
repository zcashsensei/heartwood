"""Collect a corpus of REAL endpoint responses once, so the grader can be
validated and tuned offline without paying 19s per query again.

Doctrine: inspect the payload before trusting any parser.
"""
import json
import pathlib
import sys
import time

import challenges as C
import endpoint as E

HERE = pathlib.Path(__file__).parent
OUT = HERE / "corpus.jsonl"

n = int(sys.argv[1]) if len(sys.argv) > 1 else 16
diff = int(sys.argv[2]) if len(sys.argv) > 2 else 1

pool = C.make_pool(424242, n, diff)
with OUT.open("w", encoding="utf-8") as f:
    for mode in ("honest", "hollow"):
        for it in pool:
            t0 = time.time()
            try:
                r, tok = E.query(it["q"], mode, seed=it["id"] + 31337)
            except Exception as e:
                r, tok = f"<ERROR {type(e).__name__}>", 0
            rec = {"mode": mode, "id": it["id"], "family": it["family"],
                   "q": it["q"], "truth": it["a"], "resp": r,
                   "tokens": tok, "secs": round(time.time() - t0, 1)}
            f.write(json.dumps(rec) + "\n")
            f.flush()
            print(f"{mode} {it['id']:3d} {it['family']:12s} "
                  f"{rec['secs']:5.1f}s tok={tok:4d}", flush=True)
print("DONE", OUT)
