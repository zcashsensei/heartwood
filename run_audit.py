"""Heartwood audit driver: calibrate -> commit -> beacon -> audit -> receipt.

Ordering is the security property. The pool is committed BEFORE the beacon
value exists, so the auditor cannot choose a favourable subset; the beacon
then fixes which items are used, so neither side controls the sample.
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

import challenges as C
import endpoint as E
import heartwood as H

HERE = pathlib.Path(__file__).parent

# Endpoint under audit. Defaults to the local Ollama path; set_provider()
# swaps in a real API without changing any protocol logic -- the audit does
# not care what is behind the endpoint, which is the point.
_PROVIDER = None


def set_provider(p):
    global _PROVIDER
    _PROVIDER = p


def ask(question, mode):
    if _PROVIDER is None:
        return E.query(question, mode)[0]
    return _PROVIDER.query(question, mode)[0]


def code_hash():
    h = hashlib.sha256()
    for f in ("challenges.py", "endpoint.py", "heartwood.py"):
        h.update((HERE / f).read_bytes())
    return h.hexdigest()


def calibrate(n, difficulty, seed, mode="honest", verbose=True, families=None):
    """Measure the claimed model's capability on a DISJOINT pool."""
    pool = C.make_pool(seed, n, difficulty, families)
    ok = 0
    for it in pool:
        r = ask(it["q"], mode)
        ok += E.grade(E.extract(r), it["a"], r)
    p0 = H.lower_conf_bound(ok, n, conf=0.99)
    if verbose:
        print(f"  calibration: {ok}/{n} = {ok/n:.3f} raw, "
              f"p0 (99% lower bound) = {p0:.3f}", flush=True)
    return p0, ok, n


def audit(p0, p1, alpha, pool_seed, pool_size, difficulty,
          serve_mode, dilution=0.0, max_q=120, verbose=True, families=None):
    """Run the pre-committed audit against a (possibly dishonest) endpoint."""
    import random as _r
    pool = C.make_pool(pool_seed, pool_size, difficulty, families)
    commitment = C.pool_commitment(pool)
    beacon = H.fetch_beacon()
    order = H.selection_order(commitment, beacon, len(pool))

    lam = H.kelly_lambda(p0, p1)
    thr = __import__("math").log10(1.0 / alpha)
    plan = {"p0": p0, "p1": p1, "alpha": alpha, "lambda": lam,
            "pool_size": pool_size, "max_queries": max_q,
            "families": families}

    mixer = _r.Random(int(commitment[:8], 16))
    transcript, lw = [], 0.0
    for k, item_id in enumerate(order[:max_q]):
        it = pool[item_id]
        # dilution: only a fraction of traffic is silently downgraded
        mode = "hollow" if (serve_mode == "hollow" or
                            (serve_mode == "dilute" and
                             mixer.random() < dilution)) else "honest"
        resp = ask(it["q"], mode)
        g = E.grade(E.extract(resp), it["a"], resp)
        transcript.append({
            "item_id": item_id,
            "served_mode": mode,
            "question_sha256": H.sha(it["q"]),
            "response": resp,
            "response_sha256": H.sha(resp),
            "graded": g,
        })
        lw += __import__("math").log10(1.0 + lam * (p0 - g))
        if verbose and (k + 1) % 10 == 0:
            print(f"    q={k+1:3d}  rate={sum(t['graded'] for t in transcript)/(k+1):.2f}"
                  f"  log10W={lw:+.2f}/{thr:.0f}", flush=True)
        if lw >= thr:
            break

    return H.build_receipt(pool_seed, difficulty, commitment, beacon,
                           plan, {"n": None}, transcript, code_hash())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--difficulty", type=int, default=1)
    ap.add_argument("--calib", type=int, default=40)
    ap.add_argument("--pool", type=int, default=200)
    ap.add_argument("--maxq", type=int, default=100)
    ap.add_argument("--p1", type=float, default=0.5)
    ap.add_argument("--alpha", type=float, default=0.01)
    ap.add_argument("--scenarios", default="honest,hollow")
    ap.add_argument("--dilution", type=float, default=0.3)
    ap.add_argument("--families", default="state_track,money_chain")
    ap.add_argument("--provider", default="ollama",
                    help="ollama | anthropic")
    ap.add_argument("--model", default=None)
    ap.add_argument("--p0", type=float, default=None,
                    help="reuse an ALREADY-COMMITTED p0 instead of "
                         "recalibrating; keeps the frozen plan intact")
    a = ap.parse_args()
    fams = a.families.split(",") if a.families else None
    if a.provider != "ollama":
        import providers
        kw = {"model": a.model} if a.model else {}
        set_provider(providers.get_provider(a.provider, **kw))

    print(f"HEARTWOOD audit  difficulty={a.difficulty}  alpha={a.alpha}  "
          f"families={fams}")
    if a.p0 is not None:
        # Optional continuation of an earlier audit. Anytime-validity makes
        # extending the budget free: Ville's inequality holds at ANY stopping
        # time, so continuing after seeing an inconclusive result does not
        # inflate type-I error. The plan (p0, p1, alpha, lambda) is unchanged.
        p0, ok, n = a.p0, None, None
        print(f"[1] reusing committed p0={p0:.3f} (no recalibration)",
              flush=True)
    else:
        print("[1] calibrating claimed model on disjoint pool...", flush=True)
        p0, ok, n = calibrate(a.calib, a.difficulty, seed=555555,
                              families=fams)
    if p0 <= a.p1:
        print(f"  ABORT: calibrated p0={p0:.3f} <= tolerance p1={a.p1}. "
              f"No capability cliff to test on. Lower difficulty.")
        sys.exit(2)

    out = {}
    for sc in a.scenarios.split(","):
        print(f"[2] auditing endpoint: {sc}", flush=True)
        t0 = time.time()
        rec = audit(p0, a.p1, a.alpha, 20260808, a.pool, a.difficulty,
                    sc, dilution=a.dilution, max_q=a.maxq, families=fams)
        rec["calibration"] = {
            "n": n, "successes": ok,
            "raw_rate": (ok / n) if (ok is not None and n) else None,
            "method": "wilson_lower_99" if n else "reused_committed_p0"}
        r = rec["result"]
        print(f"  -> {r['verdict']}  n={r['n_queries']}  "
              f"rate={r['observed_rate']:.3f}  "
              f"log10W={r['peak_log10_wealth']:+.2f}  "
              f"fired_at={r['rejected_at']}  ({time.time()-t0:.0f}s)", flush=True)
        p = HERE / f"receipt_{sc}.json"
        p.write_text(json.dumps(rec, indent=1))
        v = H.verify_receipt(rec)
        print(f"  -> independent verify: valid={v['valid']} {v['checks']}",
              flush=True)
        out[sc] = (r, v)
