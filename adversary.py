"""Adversarial tests against a Heartwood receipt.

A receipt is only worth something if forging one is hard. These are the attacks
a dishonest AUDITOR would run to frame an honest provider, and the attacks a
dishonest PROVIDER would run to launder a bad audit. Every one must be caught
by verify_receipt() alone -- offline, with no access to auditor or provider.
"""
import copy
import json
import pathlib
import sys

import challenges as C
import heartwood as H

HERE = pathlib.Path(__file__).parent


def attack(name, receipt, mutate, expect_caught_by=None):
    r = copy.deepcopy(receipt)
    mutate(r)
    v = H.verify_receipt(r)
    failed = [k for k, ok in v["checks"].items() if not ok]
    caught = not v["valid"]
    status = "CAUGHT" if caught else "MISSED"
    flag = "ok " if caught else "!! "
    print(f"  {flag}{status:7s} {name:44s} failed_checks={failed}")
    return caught


def main(path):
    receipt = json.loads(pathlib.Path(path).read_text())
    base = H.verify_receipt(receipt)
    print(f"baseline receipt valid={base['valid']}  "
          f"verdict={base['verdict']}  evidence={base['evidence_vs_alpha']}")
    if not base["valid"]:
        print("  baseline is invalid; fix before running adversary")
        print("  checks:", base["checks"])
        return 1
    print()
    print("ATTACKS (every one must be CAUGHT):")

    results = []

    # --- dishonest auditor: manufacture evidence against an honest provider ---
    def flip_bit(r):
        for t in r["transcript"]:
            if t["graded"] == 1:
                t["graded"] = 0
                break
    results.append(attack("auditor flips a correct answer to wrong",
                          receipt, flip_bit))

    def forge_response(r):
        r["transcript"][0]["response"] = "ANSWER: 999999"
    results.append(attack("auditor rewrites a response body",
                          receipt, forge_response))

    def forge_response_flip_grade(r):
        # Rewrite a response the endpoint got RIGHT into a wrong one, fix the
        # hash, and flip the grade to match. Self-consistent at the item level.
        pool = C.make_pool(r["pool"]["seed"], r["pool"]["size"],
                           r["pool"]["difficulty"], r["pool"].get("families"))
        by_id = {it["id"]: it for it in pool}
        for t in r["transcript"]:
            if t["graded"] == 1:
                it = by_id[t["item_id"]]
                wrong = "ANSWER: 0" if it["a"] != "0" else "ANSWER: 1"
                t["response"] = wrong
                t["response_sha256"] = H.sha(wrong)
                t["graded"] = 0
                break
    results.append(attack("auditor rewrites a passed item, hash AND grade",
                          receipt, forge_response_flip_grade))

    def cherry_pick(r):
        # keep only the items the endpoint got wrong
        r["transcript"] = [t for t in r["transcript"] if t["graded"] == 0]
        res = H.build_receipt(
            r["pool"]["seed"], r["pool"]["difficulty"], r["pool"]["commitment"],
            r["beacon"], r["plan"], r["calibration"], r["transcript"],
            r["code_hash"])
        r["result"] = res["result"]
    results.append(attack("auditor drops every item the endpoint passed",
                          receipt, cherry_pick))

    def reorder(r):
        r["transcript"] = list(reversed(r["transcript"]))
    results.append(attack("auditor reorders items to a favourable sequence",
                          receipt, reorder))

    def swap_beacon(r):
        r["beacon"] = dict(r["beacon"])
        r["beacon"]["randomness"] = "00" * 18
    results.append(attack("auditor swaps in a beacon of their choosing",
                          receipt, swap_beacon))

    def inflate_p0(r):
        r["plan"] = dict(r["plan"])
        r["plan"]["p0"] = 0.99  # claim the model is better than it is
    results.append(attack("auditor inflates p0 to manufacture a deficit",
                          receipt, inflate_p0))

    def tune_lambda(r):
        r["plan"] = dict(r["plan"])
        r["plan"]["lambda"] = r["plan"]["lambda"] * 1.5
    results.append(attack("auditor re-tunes the bet after seeing outcomes",
                          receipt, tune_lambda))

    def restate_verdict(r):
        r["result"] = dict(r["result"])
        r["result"]["verdict"] = "EFFORT_DEFICIT"
        r["result"]["rejected_at"] = 1
    results.append(attack("auditor simply asserts a different verdict",
                          receipt, restate_verdict))

    def swap_pool(r):
        r["pool"] = dict(r["pool"])
        r["pool"]["seed"] = r["pool"]["seed"] + 1
    results.append(attack("auditor substitutes a different challenge pool",
                          receipt, swap_pool))

    # --- dishonest provider: launder a failing audit into a pass ----------
    def provider_hides_failures(r):
        for t in r["transcript"]:
            t["graded"] = 1
        res = H.build_receipt(
            r["pool"]["seed"], r["pool"]["difficulty"], r["pool"]["commitment"],
            r["beacon"], r["plan"], r["calibration"], r["transcript"],
            r["code_hash"])
        r["result"] = res["result"]
    results.append(attack("provider marks every failed answer as correct",
                          receipt, provider_hides_failures))

    print()
    caught, total = sum(results), len(results)
    print(f"IN-SCOPE RESULT: {caught}/{total} attacks caught")

    # ---------------------------------------------------------------- #
    # KNOWN BOUNDARY -- documented, not a bug.                          #
    # Heartwood binds the auditor's PROTOCOL, not the provider's SPEECH.#
    # A dishonest auditor who fabricates a fully self-consistent        #
    # transcript cannot be caught by the receipt alone. Closing this    #
    # needs a transport-binding layer: provider signatures (AEX) or a   #
    # TLS-transcript proof (TLSNotary / zkTLS).                         #
    # ---------------------------------------------------------------- #
    print()
    print("KNOWN BOUNDARY (expected to succeed -- needs AEX/zkTLS to close):")

    def full_fabrication(r):
        pool = C.make_pool(r["pool"]["seed"], r["pool"]["size"],
                           r["pool"]["difficulty"], r["pool"].get("families"))
        by_id = {it["id"]: it for it in pool}
        for t in r["transcript"]:
            it = by_id[t["item_id"]]
            wrong = "ANSWER: 0" if it["a"] != "0" else "ANSWER: 1"
            t["response"] = wrong
            t["response_sha256"] = H.sha(wrong)
            t["graded"] = 0
        res = H.build_receipt(
            r["pool"]["seed"], r["pool"]["difficulty"], r["pool"]["commitment"],
            r["beacon"], r["plan"], r["calibration"], r["transcript"],
            r["code_hash"])
        r["result"] = res["result"]

    fab = copy.deepcopy(receipt)
    full_fabrication(fab)
    fv = H.verify_receipt(fab)
    print(f"  auditor fabricates an entire self-consistent transcript "
          f"against an honest provider")
    print(f"    receipt verifies : {fv['valid']}   verdict: {fv['verdict']}")
    print(f"    -> Heartwood alone CANNOT catch this. It proves the auditor")
    print(f"       followed the protocol, not that the provider spoke.")
    print(f"       Compose with AEX (provider signature) or zkTLS.")

    return 0 if caught == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else HERE / "receipt_hollow.json"))
