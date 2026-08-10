"""Standalone Heartwood receipt verifier.

    python verify.py evidence/receipt_hollow.json
    python verify.py                    # verifies a bundled receipt

Runs entirely offline. It needs no access to the auditor, the provider, or the
network -- which is the whole point: the evidence is transferable.
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


def main(path):
    p = pathlib.Path(path)
    if not p.exists():
        # A dead end here teaches nothing. List what the clone actually ships
        # so the next command is obvious.
        print(f"no such receipt: {p}\n\nreceipts bundled with this clone:")
        for r in available():
            print(f"    {r}")
        return 2
    receipt = json.loads(p.read_text())
    v = H.verify_receipt(receipt)
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
    print(f"  RECEIPT VALID   : {v['valid']}")
    return 0 if v["valid"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT))
