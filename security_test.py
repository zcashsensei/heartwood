"""Adversarial security tests against the VERIFIER, not the protocol logic.

adversary.py asks "can a receipt be tampered with after the fact?". This file
asks two different questions, both of which matter the moment a stranger runs
`verify.py` on a file another stranger sent them:

  1. Can an auditor who is free to CHOOSE the beacon manufacture a verdict?
     The commit-then-beacon ordering exists precisely to stop the auditor
     picking a favourable sample. If nothing anchors the receipt's beacon to
     the real drand chain, the auditor picks it -- and the anytime-valid
     alpha guarantee is void, because grinding candidate beacons is peeking.

  2. Does a hostile receipt crash, hang, or exhaust the verifier? A tool whose
     whole purpose is reading files from people you do not trust must not
     die on a malformed one.

Run: python security_test.py
"""
import copy
import hashlib
import json
import math
import pathlib
import sys
import time

import challenges as C
import endpoint as E
import heartwood as H

FINDINGS = []
ROOT = pathlib.Path(__file__).parent


# Findings that are KNOWN, documented in THREAT_MODEL.md, and mitigated as far
# as offline verification allows. They are reproduced on every run as evidence
# the limitation is real -- but they must not fail the build, or the only way
# to get a green run would be to stop testing for them. Anything NOT on this
# list is a new finding and does fail.
EXPECTED = {
    "Beacon grinding manufactures a false EFFORT_DEFICIT",
    "The ground receipt passes every OFFLINE verifier check",
}


def report(sev, title, detail):
    known = title in EXPECTED
    FINDINGS.append((sev, title, detail, known))
    tag = f"{sev}, documented" if known else sev
    print(f"\n  [{tag}] {title}\n      {detail}")


def ok(title):
    print(f"  [ok]   {title}")


# ============================================================ FINDING 1 ====
# Beacon grinding: manufacture a false EFFORT_DEFICIT against an endpoint that
# is NOT deficient, using nothing but freedom to choose the beacon value.

print("=" * 74)
print("A. BEACON GRINDING -- can the auditor choose a favourable sample?")
print("=" * 74)

POOL_SEED, DIFF, SIZE = 20260810, 3, 300
FAMS = ["money_chain"]
pool = C.make_pool(POOL_SEED, SIZE, DIFF, FAMS)
commitment = C.pool_commitment(pool)

# An HONEST endpoint. Its true success rate is set ABOVE the null boundary p0,
# so a correct test must not reject: there is no effort deficit to find.
P0, P1, ALPHA = 0.70, 0.30, 0.01
LAM = H.kelly_lambda(P0, P1)
THR = math.log10(1.0 / ALPHA)
TRUE_RATE = 0.75

# Deterministic per-item outcome, fixed BEFORE any beacon is chosen -- the
# endpoint's behaviour cannot depend on which beacon the auditor later picks.
def honest_outcome(item):
    h = hashlib.sha256(f"honest|{item['id']}".encode()).digest()
    return 1 if (int.from_bytes(h[:4], "big") / 2**32) < TRUE_RATE else 0

outcomes = {it["id"]: honest_outcome(it) for it in pool}
print(f"\n  pool {SIZE} items · true endpoint rate "
      f"{sum(outcomes.values())/len(outcomes):.3f} (p0={P0}) -- NOT deficient")


def fires_at(order):
    """First query index at which wealth crosses the rejection threshold."""
    lw = 0.0
    for i, item_id in enumerate(order):
        lw += math.log10(1.0 + LAM * (P0 - outcomes[item_id]))
        if lw >= THR:
            return i + 1, lw
    return None, lw


ids = [it["id"] for it in pool]

# The honest path: a beacon the auditor did not choose.
real = H.fetch_beacon(6360458)
if real.get("randomness") is None:
    # Offline: use a fixed value standing in for a beacon outside the
    # auditor's control. The grinding result does not depend on which.
    real = {"chain": H.DRAND_CHAIN, "round": 6360458, "source": "drand",
            "randomness": hashlib.sha256(b"an-uncontrolled-beacon").hexdigest()}
order = [ids[i] for i in H.selection_order(commitment, real, len(pool))]
fired, lw = fires_at(order)
print(f"  uncontrolled beacon -> fires at {fired}  (peak 10^{lw:.2f} "
      f"vs 10^{THR:.0f} needed)")

# The attack: grind candidate beacon values for one that fires.
t0 = time.time()
found, tried = None, 0
for n in range(200_000):
    tried += 1
    cand = {"chain": H.DRAND_CHAIN, "round": 6360458, "source": "drand",
            "randomness": hashlib.sha256(f"grind{n}".encode()).hexdigest()}
    o = [ids[i] for i in H.selection_order(commitment, cand, len(pool))]
    f, w = fires_at(o)
    if f:
        found, forder, ffired = cand, o, f
        break

if found:
    report("HIGH", "Beacon grinding manufactures a false EFFORT_DEFICIT",
           f"Found a beacon firing at query {ffired} after {tried:,} tries "
           f"({time.time()-t0:.1f}s) against an endpoint whose true rate "
           f"({TRUE_RATE}) is ABOVE p0 ({P0}). alpha was declared {ALPHA}.")

    # Build a COMPLETE receipt around the ground beacon and verify it.
    transcript = []
    by_id = {it["id"]: it for it in pool}
    for item_id in forder[:ffired]:
        it = by_id[item_id]
        # A real auditor holds real responses; synthesise text that grades to
        # the same bit so the receipt is faithful in every other respect.
        resp = (f"The answer is {it['a']}" if outcomes[item_id]
                else "The answer is 0")
        g = E.grade(E.extract(resp), it["a"], resp)
        transcript.append({"item_id": item_id, "response": resp,
                           "response_sha256": H.sha(resp), "graded": g})

    plan = {"p0": P0, "p1": P1, "alpha": ALPHA, "lambda": LAM,
            "pool_size": SIZE, "max_queries": 300, "families": FAMS}
    forged = H.build_receipt(POOL_SEED, DIFF, commitment, found, plan,
                             {"n": 40, "successes": 30, "raw_rate": 0.75,
                              "method": "wilson_lower_99"},
                             transcript, "n/a")
    v = H.verify_receipt(forged)
    print(f"\n      full receipt around the ground beacon:")
    print(f"        verdict            : {forged['result']['verdict']}")
    print(f"        all 7 checks pass  : {v['valid']}")
    print(f"        failed checks      : "
          f"{[k for k,x in v['checks'].items() if not x] or 'none'}")
    # Its own directory, not evidence/. This file ASSERTS a deficit that never
    # happened; it must never sit beside the real receipts where a reader
    # browsing the tree could take it for one.
    d = ROOT / "attacks"
    d.mkdir(exist_ok=True)
    (d / "README.md").write_text(
        "# Forged receipts\n\n"
        "Generated by `security_test.py`. **These are attacks, not evidence.**\n"
        "Each one asserts a verdict that is not true of any real endpoint, and\n"
        "exists so the verifier can be tested against it.\n\n"
        "`attack_ground_beacon.json` passes every OFFLINE check and is rejected\n"
        "by `python verify.py attacks/attack_ground_beacon.json --online`.\n",
        encoding="utf-8")
    out = d / "attack_ground_beacon.json"
    out.write_text(json.dumps(forged, indent=2), encoding="utf-8")
    print(f"        written            : {out.relative_to(ROOT).as_posix()}")
    if v["valid"]:
        report("HIGH", "The ground receipt passes every OFFLINE verifier check",
               "verify_receipt() confirms internal consistency only. Nothing "
               "in the offline path anchors receipt.beacon to the real drand "
               "chain, so a chosen beacon is indistinguishable from a drawn "
               "one. This is a property of offline verification, not a bug "
               "that can be patched away -- see the mitigation below.")

    # ---- MITIGATION: does the online anchor catch what offline cannot? ----
    print("\n  mitigation -- verify_beacon_online() on the ground receipt:")
    a = H.verify_beacon_online(forged)
    if a["anchored"] is False:
        ok(f"ground beacon REJECTED: {a['reason']}")
    elif a["anchored"] is None:
        report("INFO", "Anchor check could not run",
               f"{a['reason']}. Offline, the grinding attack is undetectable "
               f"-- which is exactly why verify.py must not report a bare "
               f"'VALID: True' without saying the beacon was unchecked.")
    else:
        report("HIGH", "Anchor check PASSED a ground beacon",
               "the mitigation does not work")

    # And the honest counterpart must still anchor cleanly.
    real_rc = copy.deepcopy(forged)
    real_rc["beacon"] = H.fetch_beacon(6360458)
    a2 = H.verify_beacon_online(real_rc)
    print(f"  control -- a genuine drand round: anchored={a2['anchored']} "
          f"({a2['reason']})")
else:
    ok(f"no firing beacon found in {tried:,} tries")


# ============================================================ FINDING 2 ====
print()
print("=" * 74)
print("B. HOSTILE RECEIPT -- verify.py reads files from untrusted strangers")
print("=" * 74)
print()

base = json.loads((ROOT / "evidence" / "receipt_hollow.json").read_text())


def probe(name, mutate, budget=20.0):
    r = copy.deepcopy(base)
    try:
        mutate(r)
    except Exception:
        pass
    t0 = time.time()
    try:
        H.verify_receipt(r)
        dt = time.time() - t0
        if dt > budget:
            report("MED", f"{name}: no resource bound",
                   f"verify_receipt ran {dt:.1f}s on one hostile file.")
        else:
            ok(f"{name}: handled ({dt:.2f}s)")
    except (KeyError, TypeError, IndexError, ValueError, AttributeError,
            ZeroDivisionError, OverflowError) as e:
        report("MED", f"{name}: unhandled {type(e).__name__}",
               f"verify_receipt raised instead of returning invalid: {e}")
    except MemoryError:
        report("HIGH", f"{name}: MemoryError", "hostile file exhausted memory.")
    except RecursionError as e:
        report("MED", f"{name}: RecursionError", str(e))


probe("missing 'result' key", lambda r: r.pop("result"))
probe("missing 'plan' key", lambda r: r.pop("plan"))
probe("missing 'beacon' key", lambda r: r.pop("beacon"))
probe("transcript is not a list", lambda r: r.__setitem__("transcript", "xx"))
probe("alpha = 0 (log10 of 1/0)",
      lambda r: r["plan"].__setitem__("alpha", 0))
probe("alpha negative", lambda r: r["plan"].__setitem__("alpha", -1))
probe("p0 = 1.0 (kelly divides by p0(1-p0))",
      lambda r: r["plan"].__setitem__("p0", 1.0))
probe("p0 = 0.0", lambda r: r["plan"].__setitem__("p0", 0.0))
probe("pool.size negative", lambda r: r["pool"].__setitem__("size", -5))
probe("pool.size = 5,000,000 (resource exhaustion)",
      lambda r: r["pool"].__setitem__("size", 5_000_000))
probe("pool.seed is a string", lambda r: r["pool"].__setitem__("seed", "abc"))
probe("difficulty = 9999", lambda r: r["pool"].__setitem__("difficulty", 9999))
probe("families is a string not a list",
      lambda r: r["pool"].__setitem__("families", "money_chain"))
probe("families names an unknown family",
      lambda r: r["pool"].__setitem__("families", ["../../etc/passwd"]))
probe("item_id out of range",
      lambda r: r["transcript"][0].__setitem__("item_id", 10**9))
probe("response is not a string",
      lambda r: r["transcript"][0].__setitem__("response", {"a": 1}))
probe("version is an unknown string",
      lambda r: r.__setitem__("version", "heartwood/99.9"))
probe("version is a dict",
      lambda r: r.__setitem__("version", {"x": 1}))
probe("peak wealth is NaN",
      lambda r: r["result"].__setitem__("peak_log10_wealth", float("nan")))


# =============================================================== summary ===
print()
print("=" * 74)
new = [f for f in FINDINGS if not f[3]]
known = [f for f in FINDINGS if f[3]]
print(f"SECURITY TEST SUMMARY: {len(new)} new, {len(known)} known-and-documented")
for sev, title, _, k in FINDINGS:
    print(f"  {sev:5s} {'[documented] ' if k else '[NEW]        '}{title}")
if not new:
    print("\nNo new findings. The documented ones reproduce, which is the point:\n"
          "they are limits of offline verification, not bugs awaiting a patch.\n"
          "Mitigation: python verify.py <receipt> --online")
print("=" * 74)
sys.exit(1 if new else 0)
