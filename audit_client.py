"""Audit an endpoint you actually pay for, and emit a receipt.

    python audit_client.py --provider anthropic --model claude-haiku-4-5 \
        --p0 0.95 --difficulty 4 --p1 0.4

This is the real-audit path. run_audit.py is a research harness that plays both
sides of the protocol to prove it separates honest from skimmed serving; it
takes a --scenarios flag and simulates the dishonest provider. A customer has
no such flag. Here there is no mode: questions go out, answers come back, and
nothing in the loop knows whether the endpoint is being honest.

Two refusals are built in, both learned from attacking our own verifier:

  * No live beacon, no receipt. Item selection derived from a beacon the
    auditor invented is exactly the forgery security_test.py demonstrates --
    1,017 tries to manufacture a false verdict. If drand is unreachable this
    exits rather than writing a receipt nobody should trust.

  * The origin of p0 is recorded IN the receipt. p0 is the honest success rate
    the whole test is measured against, and where it came from decides what
    the receipt is worth. Calibrating through the endpoint under suspicion is
    supported because it is often all you have, but it is labelled
    `endpoint_self` and warned about, because a provider skimming during
    calibration drags p0 down to wherever it is already performing and the
    audit can never fire.

Run `--help` for the full flag list.
"""
import argparse
import hashlib
import json
import math
import pathlib
import sys
import time

import challenges as C
import endpoint as E
import endpoints as EP
import heartwood as H

HERE = pathlib.Path(__file__).parent


def code_hash():
    h = hashlib.sha256()
    for f in ("challenges.py", "endpoint.py", "heartwood.py", "endpoints.py"):
        h.update((HERE / f).read_bytes())
    return h.hexdigest()


def ask(ep, question, retries=2):
    """One query. A transport failure must never be scored as a wrong answer."""
    for attempt in range(retries + 1):
        try:
            return ep.query(question)
        except EP.EndpointError as e:
            if attempt == retries:
                raise
            print(f"    ! {e}\n    retrying ({attempt + 1}/{retries})...",
                  flush=True)
            time.sleep(2 * (attempt + 1))


def calibrate(ep, n, difficulty, seed, families):
    """Measure the endpoint on a pool DISJOINT from the audit pool."""
    pool = C.make_pool(seed, n, difficulty, families)
    ok = 0
    for i, it in enumerate(pool, 1):
        resp, _ = ask(ep, it["q"])
        ok += E.grade(E.extract(resp), it["a"], resp)
        if i % 5 == 0 or i == n:
            print(f"    calibration {i}/{n}  rate={ok / i:.2f}", flush=True)
    return H.lower_conf_bound(ok, n, conf=0.99), ok


def main(a):
    ep = EP.get_endpoint(a.provider, model=a.model, api_key=a.api_key,
                         base_url=a.base_url)
    fams = a.families.split(",") if a.families else None
    print(f"endpoint : {a.provider} · {ep.model}")
    print(f"pool     : {a.pool} items, difficulty {a.difficulty}, "
          f"families {fams or 'all'}")

    # ---- 1. p0: the honest rate everything is measured against ------------
    print("\n[1] establishing p0")
    if a.p0 is not None:
        p0, cal = a.p0, {"source": "declared", "n": None, "successes": None,
                         "raw_rate": None, "method": "operator-declared",
                         "note": a.p0_note or "supplied on the command line"}
        print(f"    p0 = {p0:.3f} (declared, not measured here)")
    else:
        print(f"    calibrating on a disjoint pool of {a.calib} items")
        print("    ! WARNING: calibrating THROUGH the endpoint under audit.")
        print("    ! A provider skimming during calibration lowers p0 to where")
        print("    ! it is already performing, and the audit can never fire.")
        print("    ! Prefer --p0 from a trusted source. Recorded as "
              "'endpoint_self'.")
        p0, ok = calibrate(ep, a.calib, a.difficulty, a.calib_seed, fams)
        cal = {"source": "endpoint_self", "n": a.calib, "successes": ok,
               "raw_rate": ok / a.calib, "method": "wilson_lower_99",
               "note": "measured through the endpoint under audit; a provider "
                       "skimming during calibration biases this downward"}
        print(f"    p0 = {p0:.3f}  (99% Wilson lower bound on "
              f"{ok}/{a.calib})")

    if p0 <= a.p1:
        print(f"\nABORT: p0={p0:.3f} <= tolerance p1={a.p1}. There is no "
              f"capability cliff\nto test on -- every query would be "
              f"uninformative. Raise --difficulty\n(a more capable model needs "
              f"harder items) or lower --p1.")
        return 2

    # ---- 2. commit --------------------------------------------------------
    print("\n[2] committing the challenge pool")
    pool = C.make_pool(a.seed, a.pool, a.difficulty, fams)
    commitment = C.pool_commitment(pool)
    print(f"    commitment = {commitment}")

    # ---- 3. beacon: live, or nothing --------------------------------------
    print("\n[3] drawing the public beacon")
    beacon = H.fetch_beacon()
    if beacon.get("randomness") is None or not beacon.get("round"):
        print(f"\nABORT: drand is unreachable ({beacon.get('source')}).\n"
              f"No receipt will be written. A receipt whose beacon the auditor\n"
              f"chose is worthless -- grinding candidate beacons manufactures a\n"
              f"false verdict in about a thousand tries (see security_test.py).\n"
              f"Re-run when the network is available.")
        return 3
    print(f"    drand round {beacon['round']}")
    print(f"    randomness  {beacon['randomness'][:32]}...")

    order = H.selection_order(commitment, beacon, len(pool))
    lam = H.kelly_lambda(p0, a.p1)
    thr = math.log10(1.0 / a.alpha)
    plan = {"p0": p0, "p1": a.p1, "alpha": a.alpha, "lambda": lam,
            "pool_size": a.pool, "max_queries": a.maxq, "families": fams}

    # ---- 4. audit ---------------------------------------------------------
    print(f"\n[4] auditing (up to {a.maxq} queries, stop at 10^{thr:.0f})")
    transcript, lw = [], 0.0
    for k, item_id in enumerate(order[:a.maxq], 1):
        it = pool[item_id]
        resp, meta = ask(ep, it["q"])
        g = E.grade(E.extract(resp), it["a"], resp)
        transcript.append({"item_id": item_id,
                           "question_sha256": H.sha(it["q"]),
                           "response": resp,
                           "response_sha256": H.sha(resp),
                           "graded": g,
                           "output_tokens": meta.get("output_tokens")})
        lw += math.log10(1.0 + lam * (p0 - g))
        rate = sum(t["graded"] for t in transcript) / k
        print(f"    q={k:3d}  {'ok ' if g else 'MISS'}  rate={rate:.2f}  "
              f"log10W={lw:+.2f}/{thr:.0f}  out_tok={meta.get('output_tokens')}",
              flush=True)
        if lw >= thr:
            print(f"    threshold crossed at query {k}")
            break

    # ---- 5. receipt -------------------------------------------------------
    receipt = H.build_receipt(a.seed, a.difficulty, commitment, beacon, plan,
                              cal, transcript, code_hash())
    receipt["endpoint"] = {"provider": a.provider, "model": ep.model,
                           "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                       time.gmtime())}
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    r = receipt["result"]
    print(f"\n[5] receipt")
    print(f"    verdict  : {r['verdict']}")
    print(f"    queries  : {r['n_queries']}  observed rate "
          f"{r['observed_rate']:.3f}")
    print(f"    evidence : 10^{r['peak_log10_wealth']:.2f} vs 10^{thr:.0f}")
    print(f"    written  : {out}")

    # Verify our own output before claiming anything about it.
    v = H.verify_receipt(receipt)
    print(f"    self-verify : {v['valid']}  "
          f"{[k for k, x in v['checks'].items() if not x] or ''}")
    anc = H.verify_beacon_online(receipt)
    print(f"    beacon      : anchored={anc['anchored']} ({anc['reason']})")

    if cal["source"] == "endpoint_self":
        print("\n    NOTE: p0 was calibrated through the audited endpoint. A"
              "\n    reader of this receipt is trusting that the endpoint was"
              "\n    honest during calibration. Recorded as 'endpoint_self'.")
    if not v["valid"] or anc["anchored"] is not True:
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Audit an LLM endpoint you pay for and emit a receipt.",
        epilog="For any OpenAI-compatible service (Groq, Together, Mistral, "
               "OpenRouter, vLLM, LM Studio) use --provider openai with "
               "--base-url.")
    ap.add_argument("--provider", default="anthropic",
                    choices=sorted(EP.ENDPOINTS))
    ap.add_argument("--model", default=None, help="model id at that provider")
    ap.add_argument("--base-url", default=None,
                    help="override the API root (OpenAI-compatible servers)")
    ap.add_argument("--api-key", default=None,
                    help="prefer the provider's env var over this flag")

    ap.add_argument("--p0", type=float, default=None,
                    help="honest success rate from a TRUSTED source. Omit to "
                         "calibrate through the audited endpoint, which is "
                         "weaker and is labelled as such in the receipt.")
    ap.add_argument("--p0-note", default=None,
                    help="where a declared p0 came from; stored in the receipt")
    ap.add_argument("--calib", type=int, default=30)
    ap.add_argument("--calib-seed", type=int, default=555555)

    ap.add_argument("--p1", type=float, default=0.4,
                    help="tolerance: the rate below which you call it a deficit")
    ap.add_argument("--alpha", type=float, default=0.01)
    ap.add_argument("--difficulty", type=int, default=3, choices=sorted(C.DIFF))
    ap.add_argument("--families", default=None,
                    help="comma-separated, e.g. money_chain,state_track")
    ap.add_argument("--pool", type=int, default=300)
    ap.add_argument("--seed", type=int, default=None,
                    help="pool seed; defaults to the current time so two "
                         "audits never share a pool")
    ap.add_argument("--maxq", type=int, default=120)
    ap.add_argument("--out", default="receipt.json")

    args = ap.parse_args()
    if args.seed is None:
        args.seed = int(time.time())
    try:
        sys.exit(main(args))
    except EP.EndpointError as e:
        print(f"\nENDPOINT ERROR: {e}")
        sys.exit(4)
    except KeyboardInterrupt:
        print("\ninterrupted -- no receipt written")
        sys.exit(130)
