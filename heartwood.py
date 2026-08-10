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
import urllib.request

import challenges as C
import portable

VERSION = "heartwood/0.3"

# Which derivations a given receipt version used. v0.2 fixed the SHUFFLE but
# left POOL GENERATION on CPython's Mersenne Twister, so v0.2 receipts were
# still Python-only in practice -- the verifier must regenerate the pool to
# check the commitment and to re-grade. v0.3 closes that. Older receipts stay
# verifiable against the derivations they were actually issued under.
LEGACY_SHUFFLE = ("heartwood/0.1",)
LEGACY_POOL = ("heartwood/0.1", "heartwood/0.2")
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


def selection_order(pool_commitment: str, beacon: dict, n: int,
                    version: str = VERSION):
    """Which items get used, and in what order.

    Derived from H(pool_commitment || beacon randomness). The auditor commits
    to the pool BEFORE the beacon value exists, so they cannot pick a
    favourable subset; the provider cannot predict the subset either.

    v0.2 specifies the shuffle as HMAC-SHA256-CTR + Fisher-Yates with
    rejection sampling (see portable.py). v0.1 used Python's random.shuffle,
    which is reproducible only under CPython -- a real interop defect in a
    protocol whose whole point is that anyone can recheck it.

    Changing the derivation would silently invalidate every receipt already
    issued, so verification stays VERSION-AWARE: a v0.1 receipt is still
    checked against the v0.1 derivation. A protocol that cannot verify its own
    history is not a protocol.
    """
    if str(version) in LEGACY_SHUFFLE:
        import random as _r
        mat = f"{pool_commitment}|{beacon.get('randomness')}".encode()
        seed = int.from_bytes(hashlib.sha256(mat).digest()[:8], "big")
        idx = list(range(n))
        _r.Random(seed).shuffle(idx)
        return idx
    seed = portable.selection_seed(pool_commitment, beacon.get("randomness"))
    return portable.shuffle_indices(seed, n)


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


# A receipt is a file one stranger hands another -- it is hostile input by
# design, and the verifier is the program that reads it. Bound the work a
# receipt can ask for. Real pools are 120-300 items; 50,000 is far past any
# honest use and still checks in well under a second.
MAX_POOL = 50_000
MAX_TRANSCRIPT = 100_000


def validate_receipt(receipt) -> list:
    """Structural validation. Returns a list of problems; empty means sane.

    Without this, verify_receipt raised raw KeyError/ZeroDivisionError/
    TypeError on malformed input -- 13 distinct crashes, plus a 57-second hang
    on a receipt merely declaring a five-million-item pool. A verifier that
    dies on a hostile file is a denial of service against the person doing the
    checking, and an uncaught traceback tells them nothing about what is wrong.
    """
    P = []
    if not isinstance(receipt, dict):
        return ["receipt is not a JSON object"]

    for key, typ in (("pool", dict), ("beacon", dict), ("plan", dict),
                     ("transcript", list), ("result", dict)):
        if key not in receipt:
            P.append(f"missing required key: {key}")
        elif not isinstance(receipt[key], typ):
            P.append(f"{key} must be a {typ.__name__}")
    if not isinstance(receipt.get("version", VERSION), str):
        P.append("version must be a string")
    if P:
        return P

    pool, plan, tr = receipt["pool"], receipt["plan"], receipt["transcript"]

    seed = pool.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        P.append("pool.seed must be an integer")
    size = pool.get("size")
    if not isinstance(size, int) or isinstance(size, bool):
        P.append("pool.size must be an integer")
    elif not 1 <= size <= MAX_POOL:
        P.append(f"pool.size {size} outside 1..{MAX_POOL}")
    diff = pool.get("difficulty")
    if not isinstance(diff, int) or isinstance(diff, bool):
        P.append("pool.difficulty must be an integer")
    elif diff not in C.DIFF:
        P.append(f"pool.difficulty {diff} is not a defined tier "
                 f"{sorted(C.DIFF)}")
    fams = pool.get("families")
    if fams is not None:
        if not isinstance(fams, list) or not all(isinstance(f, str) for f in fams):
            P.append("pool.families must be null or a list of strings")
        else:
            known = {g.__name__ for g in C.GENERATORS}
            unknown = [f for f in fams if f not in known]
            if unknown:
                P.append(f"pool.families names unknown families: {unknown}")
    if not isinstance(pool.get("commitment"), str):
        P.append("pool.commitment must be a string")

    # p0 and p1 sit strictly inside (0,1): kelly_lambda divides by p0(1-p0),
    # and alpha feeds log10(1/alpha).
    for k, lo, hi in (("p0", 0.0, 1.0), ("p1", 0.0, 1.0), ("alpha", 0.0, 1.0)):
        v = plan.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            P.append(f"plan.{k} must be a number")
        elif not (lo < float(v) < hi) or float(v) != float(v):
            P.append(f"plan.{k}={v} must lie strictly between {lo} and {hi}")
    if not isinstance(plan.get("lambda"), (int, float)) or isinstance(plan.get("lambda"), bool):
        P.append("plan.lambda must be a number")

    if len(tr) > MAX_TRANSCRIPT:
        P.append(f"transcript of {len(tr)} exceeds {MAX_TRANSCRIPT}")
    for i, t in enumerate(tr[:MAX_TRANSCRIPT]):
        if not isinstance(t, dict):
            P.append(f"transcript[{i}] is not an object")
            break
        if not isinstance(t.get("item_id"), int) or isinstance(t.get("item_id"), bool):
            P.append(f"transcript[{i}].item_id must be an integer")
            break
        if not isinstance(t.get("response"), str):
            P.append(f"transcript[{i}].response must be a string")
            break
        if t.get("graded") not in (0, 1):
            P.append(f"transcript[{i}].graded must be 0 or 1")
            break
    return P


def verify_receipt(receipt: dict) -> dict:
    """Independent verification. Recomputes every claim from scratch.

    This runs with no access to the auditor, the provider, or the network --
    which is precisely what makes the evidence transferable.

    NOTE on the beacon: this function checks that the receipt is INTERNALLY
    consistent, including that item selection follows from the beacon the
    receipt names. It does NOT confirm that beacon is a real drand output --
    see verify_beacon_online(). An auditor free to invent a beacon value can
    grind candidates until one orders the items favourably, which voids the
    alpha guarantee. Anchoring is reported separately and is never implied by
    a True here.
    """
    problems = validate_receipt(receipt)
    if problems:
        return {"valid": False, "checks": {"well_formed": False},
                "problems": problems, "verdict": None,
                "beacon_anchored": None, "peak_log10_wealth": 0.0,
                "evidence_vs_alpha": "n/a (malformed receipt)"}

    checks, ok = {"well_formed": True}, True

    # 1. The pool really is the committed pool (questions AND answers).
    ver = receipt.get("version", VERSION)
    pool = C.make_pool(receipt["pool"]["seed"], receipt["pool"]["size"],
                       receipt["pool"]["difficulty"],
                       receipt["pool"].get("families"),
                       portable_mode=(ver not in LEGACY_POOL))
    recomputed = C.pool_commitment(pool)
    checks["pool_commitment"] = (recomputed == receipt["pool"]["commitment"])

    # 2. Item selection really was beacon-derived, not auditor-chosen.
    #    Derivation is version-scoped so older receipts remain verifiable.
    order = selection_order(receipt["pool"]["commitment"], receipt["beacon"],
                            len(pool), ver)
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
    return {"valid": ok, "checks": checks, "problems": [],
            "verdict": receipt["result"]["verdict"],
            "beacon_anchored": None,   # unknown offline -- see verify_beacon_online
            "peak_log10_wealth": peak,
            "evidence_vs_alpha": f"10^{peak:.1f} vs 10^{thr:.0f} needed"}


# ------------------------------------------------------- differential ----
#
# The absolute test needs p0: the rate an honest endpoint achieves. Where p0
# comes from decides what the receipt is worth, and calibrating through the
# endpoint under audit is circular -- a provider skimming during calibration
# drags p0 down to wherever it is already performing.
#
# A paired audit needs no p0 at all. Run the SAME committed pool, in the SAME
# beacon order, against two endpoints that both claim the same model -- a
# direct API and a gateway, say -- and ask only whether B loses to A more often
# than chance. Discard the items they agree on; they carry no information about
# which is better. Among the items where exactly one succeeded, the null is
# "B is no worse than A", under which A-wins and B-wins are equally likely.
#
# That makes p0 exactly 0.5 by construction rather than by measurement, and the
# same betting machinery applies unchanged. It is McNemar's test in
# anytime-valid form.
#
# What it does NOT do: catch two endpoints skimming equally. Nothing black-box
# can. It catches the case that actually happens commercially -- a reseller or
# gateway quietly serving less than the origin it bills as.

DIFF_P0 = 0.5


def discordant_sequence(transcript: list) -> list:
    """Items where exactly one endpoint succeeded, as 1 = B won, 0 = A won."""
    out = []
    for t in transcript:
        a, b = t["graded_a"], t["graded_b"]
        if a != b:
            out.append(1 if b else 0)
    return out


def build_differential_receipt(pool_seed, difficulty, pool_commitment, beacon,
                               plan, endpoints, transcript, code_hash):
    seq = discordant_sequence(transcript)
    path = wealth_path(seq, DIFF_P0, plan["lambda"])
    peak = max(path) if path else 0.0
    threshold = math.log10(1.0 / plan["alpha"])
    fired = next((i + 1 for i, w in enumerate(path) if w >= threshold), None)
    return {
        "version": VERSION,
        "kind": "differential",
        "pool": {"seed": pool_seed, "difficulty": difficulty,
                 "commitment": pool_commitment, "size": plan["pool_size"],
                 "families": plan.get("families")},
        "beacon": beacon,
        "plan": plan,
        "endpoints": endpoints,
        "code_hash": code_hash,
        "transcript": transcript,
        "result": {
            "n_queries": len(transcript),
            "discordant": len(seq),
            "a_wins": sum(1 for x in seq if x == 0),
            "b_wins": sum(1 for x in seq if x == 1),
            "peak_log10_wealth": peak,
            "log10_threshold": threshold,
            "rejected_at": fired,
            "verdict": "B_UNDERPERFORMS_A" if fired
                       else "NO_EVIDENCE_OF_DIFFERENCE",
        },
    }


def verify_differential_receipt(receipt: dict) -> dict:
    """Independent verification of a paired audit. Offline, like the other."""
    checks = {"well_formed": True}
    for key in ("pool", "beacon", "plan", "transcript", "result", "endpoints"):
        if key not in receipt:
            return {"valid": False, "checks": {"well_formed": False},
                    "problems": [f"missing required key: {key}"],
                    "verdict": None, "beacon_anchored": None,
                    "peak_log10_wealth": 0.0,
                    "evidence_vs_alpha": "n/a (malformed receipt)"}

    ver = receipt.get("version", VERSION)
    pool = C.make_pool(receipt["pool"]["seed"], receipt["pool"]["size"],
                       receipt["pool"]["difficulty"],
                       receipt["pool"].get("families"),
                       portable_mode=(ver not in LEGACY_POOL))
    checks["pool_commitment"] = (
        C.pool_commitment(pool) == receipt["pool"]["commitment"])

    order = selection_order(receipt["pool"]["commitment"], receipt["beacon"],
                            len(pool), ver)
    used = [t["item_id"] for t in receipt["transcript"]]
    checks["beacon_selection"] = (order[:len(used)] == used)

    import endpoint as E
    by_id = {it["id"]: it for it in pool}
    hash_ok = regrade_ok = True
    for t in receipt["transcript"]:
        it = by_id.get(t["item_id"])
        if it is None:
            regrade_ok = False
            break
        for side in ("a", "b"):
            resp = t[f"response_{side}"]
            if sha(resp) != t[f"response_{side}_sha256"]:
                hash_ok = False
            if E.grade(E.extract(resp), it["a"], resp) != t[f"graded_{side}"]:
                regrade_ok = False
    checks["response_hashes"] = hash_ok
    checks["regrading"] = regrade_ok

    # The bet must be the Kelly bet against a null of 0.5 -- not a number the
    # auditor picked after seeing which way the pairs fell.
    lam = kelly_lambda(DIFF_P0, receipt["plan"]["p1"])
    checks["lambda_matches_plan"] = abs(lam - receipt["plan"]["lambda"]) < 1e-9

    seq = discordant_sequence(receipt["transcript"])
    path = wealth_path(seq, DIFF_P0, receipt["plan"]["lambda"])
    peak = max(path) if path else 0.0
    checks["wealth_recomputed"] = (
        abs(peak - receipt["result"]["peak_log10_wealth"]) < 1e-6)
    thr = math.log10(1.0 / receipt["plan"]["alpha"])
    fired = next((i + 1 for i, w in enumerate(path) if w >= thr), None)
    checks["verdict_consistent"] = (fired == receipt["result"]["rejected_at"])

    return {"valid": all(checks.values()), "checks": checks, "problems": [],
            "verdict": receipt["result"]["verdict"],
            "beacon_anchored": None,
            "peak_log10_wealth": peak,
            "evidence_vs_alpha": f"10^{peak:.1f} vs 10^{thr:.0f} needed"}


def verify_any(receipt: dict) -> dict:
    """Verify either kind. Receipts declare their kind; absent means absolute."""
    if isinstance(receipt, dict) and receipt.get("kind") == "differential":
        return verify_differential_receipt(receipt)
    return verify_receipt(receipt)


def verify_beacon_online(receipt: dict, timeout: int = 15) -> dict:
    """Confirm the receipt's beacon is a REAL drand output, not a chosen value.

    verify_receipt() is deliberately offline, and that is a feature -- but it
    means it can only establish that a receipt is self-consistent. Item
    selection is derived from the beacon the receipt itself supplies, so an
    auditor who invents that value controls the sample.

    Measured, not hypothesised: grinding candidate beacon values against a
    300-item pool found one that fires at query 6 in 1,017 tries (about half a
    second) -- against an endpoint whose true success rate was ABOVE p0, where
    an uncontrolled beacon produced 10^-57 of evidence. The declared alpha was
    0.01; under a grinding auditor the real false-positive rate approaches 1.

    This is the check that closes it: fetch the named round from drand and
    confirm the randomness matches. It needs the network, which is why it is a
    separate call rather than folded into verify_receipt.

    Returns {"anchored": True|False|None, "reason": str}. None means the
    question could not be answered (offline, unreachable) -- which must never
    be read as a pass.
    """
    b = (receipt or {}).get("beacon") or {}
    rnd, claimed = b.get("round"), b.get("randomness")
    if not isinstance(rnd, int) or rnd <= 0 or not isinstance(claimed, str):
        return {"anchored": False,
                "reason": f"receipt names no usable drand round ({rnd!r})"}
    if b.get("chain") != DRAND_CHAIN:
        return {"anchored": False,
                "reason": f"unknown chain {b.get('chain')!r}"}
    try:
        with urllib.request.urlopen(DRAND_URL.format(round=rnd), timeout=timeout) as r:
            live = json.loads(r.read())
    except Exception as e:
        return {"anchored": None,
                "reason": f"could not reach drand ({type(e).__name__})"}
    if str(live.get("randomness", "")).lower() != claimed.lower():
        return {"anchored": False,
                "reason": (f"round {rnd} randomness does not match the receipt "
                           f"-- the beacon was chosen, not drawn")}
    return {"anchored": True, "reason": f"matches drand round {rnd}"}
