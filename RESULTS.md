# Results

All numbers below were measured, not estimated. Every claim here is
reproducible from the scripts in this repository.

## Setup

The point of the experiment is to test the attack that **defeats every existing
verification layer**: identical weights, identical binary, identical hardware —
only the computation spent per request differs.

| | |
|---|---|
| Model | `gemma:2b` (2B params, Q4_K_M) via Ollama, CPU-only |
| Machine | 7.31 GB RAM, no GPU (a larger 8B model could not be loaded) |
| Honest endpoint | full reasoning budget, `num_predict=400` |
| Hollow endpoint | reasoning suppressed, `num_predict=24` |
| Difference | **serving effort only** — same weights, same binary |
| Customer prompt | **identical** in both; the endpoint applies its own policy |
| Challenge families | `state_track`, `money_chain` at difficulty 0 |
| Plan | `alpha=0.01`, `p1=0.30`, committed before the audit |

## The capability cliff is real

Items the claimed model itself cannot solve carry no evidence — they fail under
honest and hollowed serving alike. Restricting to the model's capability band is
what makes the test informative.

| family | honest | hollow |
|---|---|---|
| `state_track` | 3/4 | 1/4 |
| `money_chain` | 2/3 | 0/3 |
| `date_offset` | 1/3 | 0/3 |
| `word_index` | 0/3 | 1/3 |
| `set_logic` | 0/3 | 0/3 |
| **all families** | **0.375** | **0.125** |
| **capability band** | **0.714** | **0.143** |

At difficulty 0 in-band (n=12/mode): **honest 0.83, hollow 0.08** — separation
+0.75. Mean response length 189 vs 56 characters.

## Calibration

Disjoint pool, 36 items: **23/36 = 0.639** raw → **p0 = 0.446** (Wilson 99%
*lower* bound). The lower bound is deliberate: overstating p0 would make honest
endpoints look guilty, so the test is biased *against* finding fault.

`λ* = (0.446 − 0.30) / (0.446 × 0.554) = 0.5909`

## Live audits

α = 0.01, so the test fires when evidence reaches 10² = 100×.

| endpoint | verdict | queries | observed rate | peak evidence | receipt |
|---|---|---|---|---|---|
| honest | NO_EVIDENCE_OF_DEFICIT | 40 | 0.725 | 10^−0.17 | valid ✓ |
| **hollow** | **EFFORT_DEFICIT** | **31** | 0.129 | 10^+2.05 | valid ✓ |
| **dilute ε=0.7** | **EFFORT_DEFICIT** | **71** | 0.268 | 10^+2.01 | valid ✓ |

**No false positive on the honest endpoint** — its evidence *decayed*, as a
supermartingale under the null should.

An earlier pass with a 40-query budget did not fire on hollow (reached
10^1.60 ≈ 40×, short of 100×). Continuing the audit is statistically free here:
**anytime-validity means optional continuation does not inflate type-I error.**
That is exactly what Ville's inequality buys, and it is why the stopping rule is
safe to publish. The plan (`p0`, `p1`, `alpha`, `λ`) was reused unchanged.

## Operating envelope (Monte Carlo at the committed parameters)

| true rate | detection | median queries | p90 |
|---|---|---|---|
| 0.13 (full skim) | 1.000 | 28 | 42 |
| 0.25 | 1.000 | 55 | 98 |
| 0.35 | 0.734 | 150 | 322 |
| 0.45 | 0.007 | — | — |

Predicted median 28 for full skim vs **31 observed**; predicted median 98 for
ε=0.7 vs **71 observed**. Theory and practice agree.

**False positives**

| true rate | FPR | guarantee |
|---|---|---|
| 0.446 (exactly at the null boundary) | 0.0096 | ≤ 0.01 ✓ |
| 0.700 | 0.0000 | ≤ 0.01 ✓ |
| 0.725 (the real honest endpoint) | 0.0000 | ≤ 0.01 ✓ |

**Evidence is cheap because it compounds**

| α | threshold | queries at the measured hollow rate |
|---|---|---|
| 0.05 | 10^1 | ~16 |
| 0.01 | 10^2 | ~25 |
| 0.001 | 10^3 | ~38 |
| 10⁻⁶ | 10^6 | ~75 |

**Honest limit on dilution.** With `p1=0.30` declared, ε ≥ 0.6 is detected and
**ε ≤ 0.5 is not** (0.028 at ε=0.5, 0.000 below). This is not a defect but the
power/tolerance trade-off: the Kelly bet is optimal against the *declared*
tolerance. Detecting milder dilution requires declaring a higher `p1` and paying
substantially more queries. A better-calibrated `p0` also buys speed — the same
test at `p0=0.655` detects a full skim in a median of **7** queries.

## Style detection vs capability detection — the decisive experiment

A naive skim that simply returns short answers is caught by a **response-length
classifier at AUC 0.941**. No protocol needed, and it proves nothing. We
initially asserted style detection was weak here; that assertion was wrong for a
naive attacker, and we measured it rather than assumed it.

So we built the attacker that matters. The **padded** endpoint commits to an
answer *before* deliberating, then emits a fluent, normal-length justification —
the same weights, a normal-looking response, and the computation skipped.

| endpoint | accuracy | mean chars |
|---|---|---|
| honest | **0.750** | 182 |
| padded skim | **0.208** | 159 |

| detector | AUC | reading |
|---|---|---|
| style — response length | **0.523** | **blind** (0.5 = coin flip) |
| style — token count | 0.610 | weak |
| **capability gap** | **+0.542** | **large** |

| attacker | style detection | capability detection |
|---|---|---|
| naive (short answers) | AUC 0.941 — caught | +0.75 |
| **padded (realistic)** | **AUC 0.523 — blind** | **+0.542** |

This is the central empirical claim of the work: **against a competent
effort-skimmer, style fingerprinting goes blind while capability testing does
not.** Style is cheap to fake. Capability is not — that is precisely why it
binds effort where cryptography cannot.

## Security of the receipt

`adversary.py`, run against a real receipt:

**11/11 in-scope forgeries caught**, offline, with no access to auditor or
provider:

- flipping a graded bit
- rewriting a response body
- rewriting a passed item plus its hash *and* grade
- dropping every item the endpoint passed (cherry-picking)
- reordering items into a favourable sequence
- swapping in a beacon of the auditor's choosing
- inflating `p0` to manufacture a deficit
- re-tuning the bet after seeing outcomes
- simply asserting a different verdict
- substituting a different challenge pool
- a provider marking every failed answer correct

**Documented boundary (expected to succeed):** an auditor who fabricates a
*fully self-consistent* transcript is **not** caught. Heartwood binds the
auditor's protocol, not the provider's speech. Closing this requires a
transport-binding layer — AEX signatures or TLSNotary/zkTLS — and note that
zkTLS today is designated-verifier, so a third party still trusts the notary.

## Test suite

`python tests.py` → **60/60 passing**, covering ground truth re-derivation
(3,600 items across four families), golden grading cases taken from real
hand-verified payloads, the supermartingale property, empirical type-I control,
log-space overflow, Wilson bounds, commitment binding (questions *and* answers),
beacon determinism and sensitivity, receipt round-trip, and the adversary suite.

## Bugs found and fixed during development

Recorded because they shaped the design:

1. **Answer-extraction bug.** The model emits `Answer: 16` *first*, then reasons
   correctly to 26. The naive extractor scored a correct answer as wrong. Fixed
   with a priority-based assertion parser; locked in by golden tests.
2. **Ground-truth bug.** `money_chain` used integer division, so $4×3 at 10% off
   yielded truth=11 when the correct answer is $10.80 — penalising a *correct*
   model on 2 of 6 calibration items. Fixed by requiring the discount to divide
   the total exactly; verified by re-deriving 3,600 truths with an independent
   parser.
3. **Float64 overflow.** Wealth grows exponentially and overflowed within a few
   hundred items. Moved to log-space accumulation.
4. **Unverified claim.** We asserted style fingerprinting was weak against
   effort downgrade, then measured AUC 0.941 for a length-only detector against
   the naive skim. The claim was narrowed to the padded attacker and the naive
   result published.
