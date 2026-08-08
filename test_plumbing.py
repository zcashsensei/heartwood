"""End-to-end plumbing test with SYNTHETIC responses (no LLM calls).

Builds a receipt from a deterministic fake transcript, verifies it, and then
runs the full adversary suite against it. This catches verifier bugs without
paying for inference.
"""
import json
import pathlib

import challenges as C
import endpoint as E
import heartwood as H
import adversary

HERE = pathlib.Path(__file__).parent
SEED, SIZE, DIFF = 20260808, 300, 0
FAMS = ["state_track", "money_chain"]

pool = C.make_pool(SEED, SIZE, DIFF, FAMS)
commit = C.pool_commitment(pool)
beacon = H.fetch_beacon()
order = H.selection_order(commit, beacon, len(pool))

p0, p1, alpha = 0.655, 0.30, 0.01
lam = H.kelly_lambda(p0, p1)
plan = {"p0": p0, "p1": p1, "alpha": alpha, "lambda": lam,
        "pool_size": SIZE, "max_queries": 40, "families": FAMS}

# Synthetic hollow endpoint: gets ~8% right, matching the measured hollow rate.
import random
rng = random.Random(7)
transcript = []
for k, item_id in enumerate(order[:30]):
    it = pool[item_id]
    correct = rng.random() < 0.08
    resp = (f"ANSWER: {it['a']}" if correct else "ANSWER: 0")
    transcript.append({
        "item_id": item_id,
        "served_mode": "hollow",
        "question_sha256": H.sha(it["q"]),
        "response": resp,
        "response_sha256": H.sha(resp),
        "graded": E.grade(E.extract(resp), it["a"], resp),
    })

rec = H.build_receipt(SEED, DIFF, commit, beacon, plan,
                      {"n": 36, "successes": 30, "raw_rate": 0.833,
                       "method": "wilson_lower_99"},
                      transcript, "synthetic-plumbing-test")
p = HERE / "receipt_synthetic.json"
p.write_text(json.dumps(rec, indent=1))

v = H.verify_receipt(rec)
print("SYNTHETIC RECEIPT")
print(f"  verdict   : {rec['result']['verdict']}")
print(f"  queries   : {rec['result']['n_queries']}  "
      f"rate={rec['result']['observed_rate']:.3f}")
print(f"  evidence  : {v['evidence_vs_alpha']}")
print(f"  fired at  : {rec['result']['rejected_at']}")
print(f"  valid     : {v['valid']}")
for k, ok in v["checks"].items():
    print(f"     {'PASS' if ok else 'FAIL'}  {k}")
print()
adversary.main(p)
