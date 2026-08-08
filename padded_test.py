"""The decisive experiment: can STYLE separate a padded effort-skim, and can
CAPABILITY?

A naive skim (short answers) is caught by a length detector at AUC 0.941, so it
proves nothing. The realistic adversary pads: it commits to an answer before
deliberating, then writes a fluent, normal-length justification.

If Heartwood is worth anything, then against the padded attacker:
    length/style AUC  ->  near 0.5   (style detectors go blind)
    capability gap    ->  large      (Heartwood still sees it)
"""
import itertools
import json
import pathlib
import sys
import time

import challenges as C
import endpoint as E

HERE = pathlib.Path(__file__).parent
n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
pool = C.make_pool(8675309, n, 0, ["state_track", "money_chain"])

rows = []
for mode in ("honest", "padded"):
    for it in pool:
        t0 = time.time()
        try:
            r, tok = E.query(it["q"], mode, seed=it["id"] + 555)
        except Exception as e:
            r, tok = f"<ERROR {type(e).__name__}>", 0
        g = E.grade(E.extract(r), it["a"], r)
        rows.append({"mode": mode, "id": it["id"], "truth": it["a"],
                     "resp": r, "tok": tok, "grade": g,
                     "chars": len(r), "secs": round(time.time() - t0, 1)})
        print(f"{mode:7s} {it['id']:3d} grade={g} chars={len(r):4d} "
              f"{rows[-1]['secs']:5.1f}s", flush=True)

(HERE / "padded_corpus.jsonl").write_text(
    "\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def auc(a, b):
    """P(random a > random b), the AUC of a one-feature detector."""
    pairs = list(itertools.product(a, b))
    return sum((x > y) + 0.5 * (x == y) for x, y in pairs) / len(pairs)


h = [r for r in rows if r["mode"] == "honest"]
p = [r for r in rows if r["mode"] == "padded"]
acc_h = sum(r["grade"] for r in h) / len(h)
acc_p = sum(r["grade"] for r in p) / len(p)
len_auc = auc([r["chars"] for r in h], [r["chars"] for r in p])
tok_auc = auc([r["tok"] for r in h], [r["tok"] for r in p])

print()
print(f"honest : accuracy={acc_h:.3f}  mean_chars={sum(r['chars'] for r in h)/len(h):.0f}")
print(f"padded : accuracy={acc_p:.3f}  mean_chars={sum(r['chars'] for r in p)/len(p):.0f}")
print()
print(f"STYLE  detector (response length) AUC = {len_auc:.3f}  "
      f"(0.5 = blind)")
print(f"STYLE  detector (token count)     AUC = {tok_auc:.3f}")
print(f"CAPABILITY gap                        = {acc_h - acc_p:+.3f}")
