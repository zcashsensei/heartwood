"""Standalone Heartwood receipt verifier.

    python verify.py evidence/receipt_hollow.json
    python verify.py                    # verifies a bundled receipt
    python verify.py <file> --online    # also anchor the beacon to drand

Runs entirely offline by default. It needs no access to the auditor, the
provider, or the network -- which is the whole point: the evidence is
transferable.

What "offline" cannot establish: item selection is derived from the beacon the
receipt itself carries, so the offline checks prove the receipt is
SELF-CONSISTENT, not that the beacon was ever drawn. An auditor free to invent
that value can grind candidates until the ordering favours the verdict they
want. --online fetches the named drand round and confirms it.
"""
import json
import pathlib
import sys

import heartwood as H

HERE = pathlib.Path(__file__).parent
# Receipts live under evidence/. The default used to be a bare filename from
# back when they sat at the repo root, so the no-argument command -- the first
# thing a new user types -- failed on a clean clone.
DEFAULT = HERE / "evidence" / "receipt_hollow.json"


def available():
    return sorted(p.relative_to(HERE).as_posix()
                  for p in (HERE / "evidence").rglob("*receipt*.json"))


def main(path, online=False):
    p = pathlib.Path(path)
    if not p.exists():
        # A dead end here teaches nothing. List what the clone actually ships
        # so the next command is obvious.
        print(f"no such receipt: {p}\n\nreceipts bundled with this clone:")
        for r in available():
            print(f"    {r}")
        return 2
    try:
        receipt = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"{p.name} is not valid JSON: {e}")
        return 2

    v = H.verify_receipt(receipt)

    # A malformed receipt is reported as a receipt problem, not as a traceback.
    if not v["checks"].get("well_formed", True):
        print(f"Heartwood receipt : {p.name}")
        print("\n  MALFORMED -- not verifiable:")
        for prob in v["problems"]:
            print(f"    - {prob}")
        print("\n  RECEIPT VALID   : False")
        return 1

    r = receipt["result"]
    print(f"Heartwood receipt : {p.name}")
    print(f"  version         : {receipt['version']}")
    print(f"  beacon          : {receipt['beacon'].get('source')} "
          f"round {receipt['beacon'].get('round')}")
    print(f"  pool commitment : {receipt['pool']['commitment'][:32]}...")
    print(f"  plan            : p0={receipt['plan']['p0']:.3f} "
          f"p1={receipt['plan']['p1']:.2f} alpha={receipt['plan']['alpha']} "
          f"lambda={receipt['plan']['lambda']:.4f}")
    print()
    print("  checks:")
    for k, ok in v["checks"].items():
        print(f"    {'PASS' if ok else 'FAIL'}  {k}")
    print()
    print(f"  queries         : {r['n_queries']}  "
          f"observed rate {r['observed_rate']:.3f}")
    print(f"  evidence        : {v['evidence_vs_alpha']}")
    print(f"  VERDICT         : {r['verdict']}"
          + (f" (fired at query {r['rejected_at']})" if r["rejected_at"] else ""))
    print()

    # The checks above establish INTERNAL consistency only. Selection is
    # derived from the beacon the receipt itself supplies, so an auditor who
    # invents that value chooses the sample -- measured at 1,017 tries to
    # manufacture a false EFFORT_DEFICIT. Never print a bare "VALID: True"
    # without saying whether the beacon was anchored to the real chain.
    anchored = None
    if online:
        a = H.verify_beacon_online(receipt)
        anchored = a["anchored"]
        state = {True: "ANCHORED", False: "NOT ANCHORED",
                 None: "UNKNOWN"}[anchored]
        print(f"  BEACON          : {state} -- {a['reason']}")
    else:
        print("  BEACON          : NOT CHECKED (offline). The checks above "
              "prove self-consistency,")
        print("                    not that this beacon was ever drawn. "
              "Re-run with --online")
        print("                    to confirm it against the drand chain.")
    print()

    full = v["valid"] and anchored is True
    print(f"  RECEIPT VALID   : {v['valid']}"
          + ("" if online else "  (internally consistent; beacon unverified)"))
    if online and v["valid"] and anchored is not True:
        print("  TRUSTWORTHY     : NO -- consistent, but the beacon is not "
              "the chain's.")
    return 0 if (full or (v["valid"] and not online)) else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--online"]
    online = "--online" in sys.argv[1:]
    sys.exit(main(args[0] if args else DEFAULT, online=online))
