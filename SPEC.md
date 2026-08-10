# Heartwood Protocol Specification — `heartwood/0.3`

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
verifier can regenerate it without receiving it — and that reproduction MUST be
language-independent.

**Changed in v0.3.** v0.1 and v0.2 generated pool items with CPython's
`random.Random` (Mersenne Twister). Because a verifier must regenerate the pool
to check the commitment *and* to re-grade, those receipts were verifiable only
under CPython — v0.2 fixed the shuffle and claimed portability while this half
was still open. v0.3 derives every item from the same HMAC-SHA256 DRBG:

```
item_seed(pool_seed, difficulty, idx)
    = SHA256( "heartwood-item|" ‖ pool_seed ‖ "|" ‖ difficulty ‖ "|" ‖ idx )

# Drawn from the DRBG keyed with item_seed, in generator call order:
randint(a, b)   = a + uniform_below(b − a + 1)        # inclusive both ends
randrange(n)    = uniform_below(n)                    # half-open
choice(seq)     = seq[ uniform_below(len(seq)) ]
sample(seq, k)  = partial Fisher-Yates: for i in 0..k−1,
                  swap slot i with slot i + uniform_below(len − i); take [:k]
```

Test vectors for both derivations — selection order *and* per-item stream — are
published in `portable.py::test_vectors()` and `evidence/v0.3/test_vectors.json`.

Verification is version-scoped across both derivations:

| receipt version | pool generation | shuffle |
|---|---|---|
| `heartwood/0.1` | CPython MT | CPython MT |
| `heartwood/0.2` | CPython MT | portable |
| `heartwood/0.3` | portable | portable |

## 5. Beacon-derived selection

The derivation is fully specified — no language-specific PRNG.

```
seed = SHA256( pool_commitment ‖ "|" ‖ beacon.randomness )      # 32 bytes

# Random source: HMAC-SHA256 in counter mode.
#   block(i) = HMAC-SHA256(key = seed, msg = uint64_be(i))      # i = 0,1,2,…
#   words    = successive 8-byte big-endian slices of the block stream

# Unbiased index in [0, m):  reject-and-redraw, never modulo alone.
#   bound = 2^64 − (2^64 mod m)
#   draw next 8-byte word v; if v >= bound redraw; else return v mod m

# Fisher-Yates, descending:
#   for i = n−1 down to 1:  j = uniform_below(i+1);  swap(idx[i], idx[j])
```

HMAC-SHA256 is in every standard library, so an independent implementation
needs no crypto dependency. Cross-language test vectors are published in
`portable.py::test_vectors()` — an implementation that reproduces them is
interoperable.

Items MUST be consumed strictly in `order`. The verifier checks
`order[:n] == [t.item_id for t in transcript]`, which simultaneously defeats:

- **cherry-picking** — dropping items the endpoint passed changes the prefix;
- **reordering** — any permutation changes the prefix;
- **beacon substitution** — a different beacon yields a different order.

> **Changed in v0.2.** v0.1 used Python's `random.Random(seed).shuffle`, which
> reproduces only under CPython — so a Rust or Go verifier could not recompute
> the order, and the receipt was not actually portable. Because this changes a
> derivation, verification is **version-scoped**: a verifier MUST check a
> `heartwood/0.1` receipt against the v0.1 derivation and a `heartwood/0.2`
> receipt against the one above. A protocol that cannot verify its own history
> is not a protocol.

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

### 8.1 Offline checks (normative)

A verifier MUST perform all of:

| # | Check | Defeats |
|---|---|---|
| 0 | receipt is structurally well-formed and within bounds | malformed input, resource exhaustion |
| 1 | regenerate pool from seed; `pool_commitment == commitment` | pool substitution |
| 2 | recompute beacon order **from the beacon the receipt carries**; matches transcript prefix | cherry-picking, reordering, *inconsistent* beacon swap |
| 3 | `SHA256(response) == response_sha256` for every entry | response tampering |
| 4 | re-grade every response; matches `graded` | grade flipping |
| 5 | `λ == kelly(p0, p1)` | post-hoc bet tuning |
| 6 | recompute wealth path; matches `peak_log10_wealth` | evidence inflation |
| 7 | recompute first crossing; matches `rejected_at`/`verdict` | verdict restatement |

Check 0 exists because a receipt is hostile input by construction — one party
hands it to another. A verifier MUST bound the work a receipt can demand
(`pool.size`, transcript length) and MUST return an invalid result rather than
raising or hanging on malformed input.

Passing checks 0–7 establishes that a receipt is **internally consistent**. It
does NOT establish that the beacon was ever drawn. See 8.2.

### 8.2 Beacon anchoring (normative, network required)

Check 2 recomputes the selection order from the beacon value *inside the
receipt*. An auditor who invents that value therefore satisfies check 2 by
construction, and controls the sample — which is the precise thing the
commit-then-beacon ordering exists to prevent. Grinding candidate beacon values
until the ordering favours a verdict **is** peeking, and it voids the
anytime-valid guarantee of §6.

This is measured, not hypothesised. Against a 300-item pool and an endpoint
whose true success rate (0.75) is *above* `p0` (0.70), so no deficit exists:

| beacon | evidence reached | verdict |
|---|---|---|
| uncontrolled | 10^−57.4 | no deficit, correctly |
| ground, after 1,017 tries (0.4 s) | fires at query 6 | `EFFORT_DEFICIT`, falsely |

Therefore: a verifier that has network access MUST fetch `beacon.round` from
the named chain and confirm `beacon.randomness` matches. A verifier that
cannot MUST report the beacon as *unchecked*, and MUST NOT present a receipt as
trustworthy on the strength of checks 0–7 alone.

A future revision SHOULD carry the drand BLS signature in the receipt so
anchoring can be verified offline against the chain public key. This is not yet
specified.

## 9. Differential receipts

A receipt MAY set `kind: "differential"`. Such a receipt records a **paired**
audit of two endpoints on the same committed pool in the same beacon order, and
requires no `p0`.

Items where both endpoints agree carry no information about which is better and
are discarded. Among the remainder, the null hypothesis "B is no worse than A"
makes an A-win and a B-win equally likely, so `p0 = 0.5` **by construction
rather than by measurement**. Evidence accumulates by §6 unchanged over the
discordant sequence, encoded as 1 = B succeeded, 0 = A succeeded. This is
McNemar's test in anytime-valid form.

Transcript entries carry `response_a`, `response_a_sha256`, `graded_a` and the
`_b` equivalents; `plan.p0` MUST be `0.5`; `result` carries `discordant`,
`a_wins`, `b_wins`. Verification applies §8 to both sides of every entry.

This construction cannot detect two endpoints skimming equally — no black-box
test can. It detects an endpoint underperforming a reference that claims the
same model.

## 10. Security considerations

**In scope.** A dishonest auditor cannot cherry-pick items, reorder them,
inflate `p0`, re-tune `λ`, restate the verdict, or substitute the pool. A
dishonest provider cannot launder grades. All eleven such forgeries are
exercised in `adversary.py`.

**Explicitly NOT in scope for offline verification: beacon choice.** See §8.2.
An auditor who invents a beacon defeats the sampling guarantee, and only §8.2
anchoring closes it. `security_test.py` reproduces the attack.

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

## 11. Versioning

`version` is `heartwood/MAJOR.MINOR`. A verifier MUST refuse a `MAJOR` it does
not implement. Changes to the commitment construction, the selection derivation,
the e-value definition, or the checks in §8.1 are breaking and require a
`MAJOR` bump.
