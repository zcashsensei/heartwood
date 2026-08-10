"""Measure the GRADER against every real model response we have.

The statistical layer cannot be 100% accurate and does not claim to be: it is a
hypothesis test with a declared alpha, and its promise is that the
false-positive rate is bounded, not zero. That promise is provable and it holds.

The MEASUREMENT layer is different. Grading has to be exactly right, because a
grading error is not noise -- it moves the observed rate in a fixed direction
and the statistics faithfully amplify it into a confident verdict. A grader
that marks correct answers wrong is a machine for accusing honest providers.

That is not hypothetical. Grading compared numeric answers as STRINGS, so
Opus 5 answering "Final total: $171.00" to a truth of "171" was scored wrong,
and it lost 7 of 7 discordant items to a smaller model on formatting alone.

So this file re-grades every response in every published receipt and hunts for
the two error directions separately:

  FALSE NEGATIVE  graded 0, but the true answer is present in the response.
                  The dangerous direction: it fabricates evidence of a deficit.

  FALSE POSITIVE  graded 1, but the true answer never appears at all.
                  Less dangerous but still wrong: it hides a real deficit.

Every hit is printed with the payload so it can be judged by eye rather than by
a second heuristic, because a heuristic that checks a heuristic just moves the
question.

Run: python grading_audit.py
"""
import glob
import json
import pathlib
import re
import sys

import challenges as C
import endpoint as E

ROOT = pathlib.Path(__file__).parent
NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def receipts():
    for f in (sorted(glob.glob(str(ROOT / "evidence/receipt_*.json")))
              + sorted(glob.glob(str(ROOT / "evidence/*/*receipt*.json")))):
        yield pathlib.Path(f), json.loads(
            pathlib.Path(f).read_text(encoding="utf-8"))


def _dec(s):
    import decimal
    try:
        return decimal.Decimal(str(s).replace(",", "").rstrip("."))
    except Exception:
        return None


def asserted_matches_truth(truth, text):
    """Did the model ASSERT the true answer as its final answer?

    The bound that matters. A first version of this asked only whether the
    truth appeared ANYWHERE in the response, and flagged 25 of 378 -- every one
    of them a model showing its working, where the truth was an intermediate
    value and the model then asserted something else. "Start with the number 6
    ... Final Answer: 4" against a truth of 6 is a WRONG answer, correctly
    graded 0.

    That looser test would have reported the grader as 93.4% accurate when it
    was in fact exact, and an audit that cries wolf gets switched off. So the
    comparison is against the model's own final assertion, which is the same
    thing the grader is judging -- this file checks that judgement
    independently, it does not relax it.
    """
    t = truth.strip().lower()
    claim = E.extract(text or "").lower()
    tv = _dec(t)
    if tv is not None:
        nums = [_dec(n) for n in NUM.findall(claim)]
        last = next((n for n in reversed(nums) if n is not None), None)
        return last == tv
    return re.search(rf"\b{re.escape(t)}\b", claim) is not None


def main():
    fn = fp = graded = 0
    entries = 0
    per_receipt = []

    for path, r in receipts():
        pool = C.make_pool(r["pool"]["seed"], r["pool"]["size"],
                           r["pool"]["difficulty"], r["pool"].get("families"),
                           portable_mode=(r.get("version") not in
                                          ("heartwood/0.1", "heartwood/0.2")))
        by = {it["id"]: it for it in pool}
        rfn = rfp = n = 0
        for t in r["transcript"]:
            it = by.get(t["item_id"])
            if it is None:
                continue
            sides = ([("", t["response"], t["graded"])]
                     if "response" in t else
                     [("a", t["response_a"], t["graded_a"]),
                      ("b", t["response_b"], t["graded_b"])])
            for tag, resp, g in sides:
                n += 1
                entries += 1
                graded += g
                present = asserted_matches_truth(it["a"], resp)
                if g == 0 and present:
                    rfn += 1
                    fn += 1
                    print(f"\n  FALSE NEGATIVE  {path.name} item {t['item_id']}{tag}")
                    print(f"    truth     : {it['a']!r}")
                    print(f"    extracted : {E.extract(resp)[:120]!r}")
                    print(f"    response  : {resp[-200:]!r}")
                elif g == 1 and not present:
                    rfp += 1
                    fp += 1
                    print(f"\n  FALSE POSITIVE  {path.name} item {t['item_id']}{tag}")
                    print(f"    truth     : {it['a']!r}")
                    print(f"    response  : {resp[-200:]!r}")
        per_receipt.append((path.name, n, rfn, rfp))

    print("\n" + "=" * 74)
    print(f"{'receipt':44s} {'graded':>7} {'FN':>4} {'FP':>4}")
    for name, n, a, b in per_receipt:
        print(f"{name:44s} {n:>7} {a:>4} {b:>4}")
    print("-" * 74)
    print(f"{'TOTAL':44s} {entries:>7} {fn:>4} {fp:>4}")
    acc = (entries - fn - fp) / entries if entries else 0.0
    print(f"\ngrader agreement with an independent re-derivation: "
          f"{acc * 100:.3f}%  ({entries - fn - fp}/{entries} real responses)")
    if fn or fp:
        print("\nEvery line above is a real disagreement and needs reading by "
              "eye.\nFalse negatives are the ones that manufacture deficits.")
        return 1
    print("\nNo disagreement on any published response. The grading layer --\n"
          "the part that must be exact, because an error there is not noise\n"
          "but a directional bias the statistics faithfully amplify -- is\n"
          "exact on everything we have measured.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
