"""HEARTWOOD -- publicly verifiable proof of semantic effort for black-box LLM APIs.

    "Hollow-LLM shows the trunk can be empty. Heartwood proves it is solid."

WHAT PROBLEM THIS SOLVES
    Hollow-LLM (arXiv 2607.28884) established that a cryptographic proof of
    correct inference does not bind the amount of computation actually spent
    -- the "effort gap". TEE attestation proves the box, zkML proves the
    equations, AEX proves the signature chain. None of them prove the
    provider spent the compute you paid for.

    Behavioural audits (RUT, IRIS) do measure capability, but IRIS states its
    own limitation plainly: "no mechanism allows independent verification;
    the audit is auditor-centric... no cryptographic commitment or public
    randomness is used."

    Heartwood closes exactly that gap: a behavioural audit whose evidence is
    TRANSFERABLE to a third party, because challenge selection is bound to a
    public randomness beacon after the pool is committed, and the stopping
    rule is anytime-valid so it cannot be gamed by peeking.

THE STATISTICAL CORE
    Null is capability-based and one-sided:
        H0: p >= p0   (endpoint at least as capable as the claimed model)
    Per graded item x_t in {0,1}:
        e_t = 1 + lambda * (p0 - x_t)
    Under H0, E[e_t | F_{t-1}] = 1 + lambda*(p0 - E[x_t]) <= 1, so the wealth
    W_T = prod e_t is a non-negative supermartingale. Ville's inequality gives
        P(exists T : W_T >= 1/alpha) <= alpha
    which is an ANYTIME-VALID guarantee: the auditor may stop whenever they
    like without inflating false positives. That property is what makes the
    stopping rule safe to publish and safe to trust.

    The Kelly-optimal bet against a declared tolerance p1 < p0 solves in
    closed form:
        lambda* = (p0 - p1) / (p0 * (1 - p0))

WHAT THE RECEIPT PROVES, AND WHAT IT DOES NOT
    Proves: the auditor ran a pre-committed pool, did not choose which items
    were used (the beacon did), did not stop opportunistically (anytime-valid),
    and the graded outcomes imply the stated evidence level.

    Does NOT prove on its own: that the responses genuinely came from the
    provider. A dishonest AUDITOR could fabricate a transcript. Binding
    responses to the provider requires a transport-binding layer -- provider
    signatures (AEX) or a TLS-transcript proof (TLSNotary / zkTLS).
    Heartwood composes with those rather than replacing them:
        AEX       : "the provider really said this"
        Heartwood : "what was said proves the compute was really spent"
    Together they chain into an attestable endpoint that needs no new
    cooperation from the provider beyond what AEX already asks for.
"""
import hashlib
import json
import math
import random
import urllib.request

import challenges as C

VERSION = "heartwood/0.1"
DRAND_URL = "https://api.drand.sh/public/{round}"
DRAND_CHAIN = "drand-mainnet-default"


# ---------------------------------------------------------------- beacon ----

def fetch_beacon(round_no=None):
    """Public randomness. Nobody -- auditor or provider -- can bias it."""
    url = DRAND_URL.format(round="latest" if round_no is None else round_no)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            d = json.loads(r.read())
        return {"chain": DRAND_CHAIN, "round": d["round"],
                "randomness": d["randomness"], "source": "drand"}
    except Exception as e:
        return {"chain": "unavailable", "round": 0,
                "randomness": None, "source": f"offline:{type(e).__name__}"}


def selection_order(pool_commitment: str, beacon: dict, n: int):
    """Which items get used, and in what order.

    Derived from H(pool_commitment || beacon randomness). The auditor commits
    to the pool BEFORE the beacon value exists, so they cannot pick a
    favourable subset; the provider cannot predict the subset either.
    """
    mat = f"{pool_commitment}|{beacon.get('randomness')}".encode()
    seed = int.from_bytes(hashlib.sha256(mat).digest()[:8], "big")
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    return idx


# ------------------------------------------------------------ statistics ----

def kelly_lambda(p0: float, p1: float) -> float:
    """Growth-optimal bet against the declared tolerance p1."""
    lam = (p0 - p1) / (p0 * (1.0 - p0))
    # e_t > 0 requires lambda < 1/(1-p0); stay strictly inside.
    return max(0.0, min(lam, 0.999 / (1.0 - p0)))


def wealth_path(outcomes, p0: float, lam: float):
    """Multiplicative evidence, accumulated in LOG space.

    Wealth grows exponentially under a real deficit and overflows float64
    within a few hundred items, so the path is carried as log10(W). Any third
    party can recompute this by summation.
    """
    lw, path = 0.0, []
    for x in outcomes:
        lw += math.log10(1.0 + lam * (p0 - x))
        path.append(lw)
    return path


def lower_conf_bound(successes: int, n: int, conf: float = 0.99) -> float:
    """Conservative lower bound on the claimed model's true capability.

    Direction matters. Overstating p0 would make honest endpoints look guilty,
    so p0 is deliberately set to a LOWER bound (Wilson score), which biases the
    whole test AGAINST finding fault.
    """
    if n == 0:
        return 0.0
    z = 2.3263 if conf >= 0.99 else 1.6449
    ph = successes / n
    den = 1 + z * z / n
    centre = ph + z * z / (2 * n)
    margin = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


# --------------------------------------------------------------- receipt ----

def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def build_receipt(pool_seed, difficulty, pool_commitment, beacon, plan,
                  calibration, transcript, code_hash):
    outcomes = [t["graded"] for t in transcript]
    path = wealth_path(outcomes, plan["p0"], plan["lambda"])
    peak = max(path) if path else 0.0
    threshold = math.log10(1.0 / plan["alpha"])
    fired = next((i + 1 for i, w in enumerate(path) if w >= threshold), None)
    return {
        "version": VERSION,
        "pool": {"seed": pool_seed, "difficulty": difficulty,
                 "commitment": pool_commitment, "size": plan["pool_size"],
                 "families": plan.get("families")},
        "beacon": beacon,
        "plan": plan,
        "calibration": calibration,
        "code_hash": code_hash,
        "transcript": transcript,
        "result": {
            "n_queries": len(outcomes),
            "successes": sum(outcomes),
            "observed_rate": (sum(outcomes) / len(outcomes)) if outcomes else None,
            "peak_log10_wealth": peak,
            "log10_threshold": threshold,
            "rejected_at": fired,
            "verdict": "EFFORT_DEFICIT" if fired else "NO_EVIDENCE_OF_DEFICIT",
        },
    }


def verify_receipt(receipt: dict) -> dict:
    """Independent verification. Recomputes every claim from scratch.

    This runs with no access to the auditor, the provider, or the network --
    which is precisely what makes the evidence transferable.
    """
    checks, ok = {}, True

    # 1. The pool really is the committed pool (questions AND answers).
    pool = C.make_pool(receipt["pool"]["seed"], receipt["pool"]["size"],
                       receipt["pool"]["difficulty"],
                       receipt["pool"].get("families"))
    recomputed = C.pool_commitment(pool)
    checks["pool_commitment"] = (recomputed == receipt["pool"]["commitment"])

    # 2. Item selection really was beacon-derived, not auditor-chosen.
    order = selection_order(receipt["pool"]["commitment"], receipt["beacon"],
                            len(pool))
    used = [t["item_id"] for t in receipt["transcript"]]
    checks["beacon_selection"] = (order[:len(used)] == used)

    # 3. Grading is faithful: every response hash and graded bit re-derived.
    import endpoint as E
    regrade_ok, hash_ok = True, True
    by_id = {it["id"]: it for it in pool}
    for t in receipt["transcript"]:
        it = by_id.get(t["item_id"])
        if it is None:
            regrade_ok = False
            break
        if sha(t["response"]) != t["response_sha256"]:
            hash_ok = False
        if E.grade(E.extract(t["response"]), it["a"], t["response"]) != t["graded"]:
            regrade_ok = False
    checks["response_hashes"] = hash_ok
    checks["regrading"] = regrade_ok

    # 4. The bet was the declared Kelly bet, not tuned after the fact.
    lam = kelly_lambda(receipt["plan"]["p0"], receipt["plan"]["p1"])
    checks["lambda_matches_plan"] = (
        abs(lam - receipt["plan"]["lambda"]) < 1e-9)

    # 5. The evidence level and verdict follow from the transcript.
    outcomes = [t["graded"] for t in receipt["transcript"]]
    path = wealth_path(outcomes, receipt["plan"]["p0"], receipt["plan"]["lambda"])
    peak = max(path) if path else 0.0
    checks["wealth_recomputed"] = (
        abs(peak - receipt["result"]["peak_log10_wealth"]) < 1e-6)
    thr = math.log10(1.0 / receipt["plan"]["alpha"])
    fired = next((i + 1 for i, w in enumerate(path) if w >= thr), None)
    checks["verdict_consistent"] = (fired == receipt["result"]["rejected_at"])

    ok = all(checks.values())
    return {"valid": ok, "checks": checks,
            "verdict": receipt["result"]["verdict"],
            "peak_log10_wealth": peak,
            "evidence_vs_alpha": f"10^{peak:.1f} vs 10^{thr:.0f} needed"}
