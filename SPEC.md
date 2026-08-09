# Heartwood Protocol Specification v0.1

A Heartwood receipt is a self-contained claim about the computational effort an
LLM endpoint spent, verifiable offline by any third party. This document is
sufficient to write an independent implementation that produces and verifies
interoperable receipts.

Key words MUST, SHOULD, MAY are used per RFC 2119.

---

## 1. Roles

| Role | Trusted? | Holds |
|---|---|---|
| **Provider** | untrusted | the model; need not cooperate or even know an audit is happening |
| **Auditor** | untrusted | runs the protocol, publishes the receipt |
| **Verifier** | — | anyone; recomputes the receipt offline |
| **Beacon** | trusted for unpredictability only | a public randomness source (drand) |

The protocol's purpose is to make the **auditor** untrusted. It does not by
itself make the provider's *speech* attributable — see §8.

## 2. Definitions

- `H(x)` — SHA-256, output lowercase hex.
- **Item** — a tuple `(id, question, answer, family)` with a machine-checkable
  ground-truth `answer`.
- **Pool** — an ordered list of items, deterministically derived from a seed.
- **Capability band** — the subset of item families on which the *claimed* model
  succeeds reliably.
- `p0` — the claimed model's calibrated success rate on the band (a **lower**
  confidence bound).
- `p1` — the declared tolerance: the success rate at or below which the customer
  considers the service materially degraded. `0 < p1 < p0`.
- `alpha` — target false-positive rate.

## 3. Phase order (normative)

The security of the protocol rests entirely on this ordering. An implementation
that reorders these steps is NOT Heartwood.

```
1. CALIBRATE  -> choose the capability band and p0, on a pool DISJOINT from the audit pool
2. COMMIT     -> publish C = pool_commitment(pool) and the frozen plan
3. BEACON     -> obtain a beacon value that did not exist at step 2
4. AUDIT      -> query items in beacon-derived order; grade; accumulate evidence
5. RECEIPT    -> emit the receipt
```

- Step 2 MUST complete before the step-3 beacon round is published. Otherwise
  the auditor can choose a pool that suits a known beacon value.
- Step 1 MUST use a disjoint pool. Calibrating on audit items leaks the answers
  into `p0`.

## 4. Pool commitment

The commitment MUST bind questions **and** answers:

```
h = SHA256()
for item in pool:                       # in pool order
    h.update(f"{id}\x1f{question}\x1f{answer}\x1e".encode("utf-8"))
C = h.hexdigest()
```

Binding the answers is what prevents an auditor from later re-interpreting what
"correct" meant. Binding the questions prevents pool substitution.

The pool MUST be reproducible from `(seed, size, difficulty, families)` so a
verifier can regenerate it without receiving it.

## 5. Beacon-derived selection

```
seed_material = f"{C}|{beacon.randomness}".encode("utf-8")
prng_seed     = int.from_bytes(SHA256(seed_material)[:8], "big")
order         = shuffle(range(len(pool)), prng_seed)
```

Items MUST be consumed strictly in `order`. The verifier checks
`order[:n] == [t.item_id for t in transcript]`, which simultaneously defeats:

- **cherry-picking** — dropping items the endpoint passed changes the prefix;
- **reordering** — any permutation changes the prefix;
- **beacon substitution** — a different beacon yields a different order.

The shuffle MUST be a documented, reproducible algorithm. This implementation
uses Python's `random.Random(seed).shuffle`; an interoperable implementation
MUST specify and match the PRNG, or the profile MUST define a portable one
(recommended for v1: Fisher-Yates driven by ChaCha20 keyed with `prng_seed`).

## 6. Evidence accumulation

Null hypothesis, one-sided and capability-based:

```
H0 : p >= p0        "the endpoint is at least as capable as the claimed model"
```

For each graded outcome `x_t ∈ {0,1}`:

```
e_t = 1 + λ (p0 − x_t)
λ*  = (p0 − p1) / (p0 (1 − p0))          clamped to [0, 1/(1−p0))
```

Under `H0`, `E[e_t | F_{t−1}] = 1 + λ(p0 − E[x_t]) ≤ 1`, so `W_T = Π e_t` is a
non-negative supermartingale and **Ville's inequality** gives

```
P( ∃T : W_T ≥ 1/alpha ) ≤ alpha
```

Implementations MUST accumulate in log space (`Σ log10 e_t`); `W` overflows
float64 within a few hundred items.

`λ` MUST be fixed by the plan before the audit. A verifier recomputes `λ` from
`(p0, p1)` and rejects any receipt whose stated `λ` disagrees — this is what
prevents re-tuning the bet after seeing outcomes.

### 6.1 Optional continuation

Because the guarantee is **anytime-valid**, an auditor MAY extend a completed
audit with more queries under the *same* plan, and MAY stop at any time, without
inflating `alpha`. An auditor MUST NOT alter `p0`, `p1`, `alpha`, `λ`, or the
pool when continuing. Re-calibrating mid-audit voids the guarantee.

## 7. Receipt format

```jsonc
{
  "version": "heartwood/0.1",
  "pool":   { "seed": int, "size": int, "difficulty": int,
              "families": [string]|null, "commitment": hex },
  "beacon": { "chain": string, "round": int|string,
              "randomness": hex|null, "source": string },
  "plan":   { "p0": float, "p1": float, "alpha": float, "lambda": float,
              "pool_size": int, "max_queries": int, "families": [string]|null },
  "calibration": { "n": int|null, "successes": int|null,
                   "raw_rate": float|null, "method": string },
  "code_hash": hex,
  "transcript": [
    { "item_id": int, "served_mode": string,
      "question_sha256": hex, "response": string,
      "response_sha256": hex, "graded": 0|1 }
  ],
  "result": { "n_queries": int, "successes": int, "observed_rate": float,
              "peak_log10_wealth": float, "log10_threshold": float,
              "rejected_at": int|null, "verdict": string }
}
```

`verdict` ∈ `{"EFFORT_DEFICIT", "NO_EVIDENCE_OF_DEFICIT"}`.

Note the asymmetry: `NO_EVIDENCE_OF_DEFICIT` is **not** a proof of honest
service. It means the audit did not accumulate `1/alpha` evidence within the
queries spent. Receipts MUST NOT be presented as certificates of good behaviour.

## 8. Verification

A verifier MUST perform all of:

| # | Check | Defeats |
|---|---|---|
| 1 | regenerate pool from seed; `pool_commitment == commitment` | pool substitution |
| 2 | recompute beacon order; matches transcript prefix | cherry-picking, reordering, beacon swap |
| 3 | `SHA256(response) == response_sha256` for every entry | response tampering |
| 4 | re-grade every response; matches `graded` | grade flipping |
| 5 | `λ == kelly(p0, p1)` | post-hoc bet tuning |
| 6 | recompute wealth path; matches `peak_log10_wealth` | evidence inflation |
| 7 | recompute first crossing; matches `rejected_at`/`verdict` | verdict restatement |

A receipt is valid iff all seven pass. Verification MUST require no network
access and no contact with auditor or provider.

## 9. Security considerations

**In scope.** A dishonest auditor cannot cherry-pick items, reorder them, choose
the beacon, inflate `p0`, re-tune `λ`, restate the verdict, or substitute the
pool. A dishonest provider cannot launder grades. All eleven such forgeries are
exercised in `adversary.py`.

**Out of scope — the fabrication boundary.** Heartwood binds the **auditor's
protocol**, not the **provider's speech**. An auditor who fabricates a fully
self-consistent transcript produces a receipt that verifies. This is
demonstrated, not hidden, in `adversary.py`. Closing it requires a
transport-binding layer:

```
AEX / zkTLS : "the provider really said this"
Heartwood   : "what was said required the compute"
```

Note that zkTLS today is **designated-verifier**: convincing a third party still
means trusting the notary. Composition improves the trust story; it does not
make it unconditional.

**Grading integrity.** Grading MUST be deterministic and re-runnable from the
response text alone. Any LLM-judge or nondeterministic grader breaks
verifiability, because the verifier could not reproduce `graded`.

**Calibration honesty.** `p0` MUST be a lower confidence bound. Using a point
estimate inflates false positives; the lower bound biases the test *against*
finding fault, which is the safe direction.

**Indistinguishability.** Challenges SHOULD be drawn from the customer's own
traffic distribution. This implementation uses ordinary arithmetic word
problems, which is argued but not proven to be indistinguishable. A provider
profiling one customer's traffic could notice a shift.

**Power is tied to `p1`.** The bet is optimal against the declared tolerance, so
the test is weak against degradation milder than `p1`. Detecting small dilution
fractions requires a higher `p1` and substantially more queries.

## 10. Versioning

`version` is `heartwood/MAJOR.MINOR`. A verifier MUST refuse a `MAJOR` it does
not implement. Changes to the commitment construction, the selection derivation,
the e-value definition, or the seven checks are breaking and require a `MAJOR`
bump.
