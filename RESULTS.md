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

Re-run against a **frontier** receipt: **8/8 applicable attacks caught**, with
3 reported N-A. Those three need an item graded 1 to mutate (flip a correct
answer, rewrite a passed item, drop passed items), and the skimmed frontier
endpoint got all 4 items wrong — so the mutation changed nothing and the
unmodified receipt correctly verified.

The first run reported that as **8/11 MISSED**, which was a false alarm from
the harness, not a security regression. It is fixed: `attack()` now diffs the
receipt before and after and reports N-A when nothing was mutated. This
matters more than the count — **a silently-no-op attack in a security suite is
exactly how a real miss would hide.**

**Documented boundary (expected to succeed):** an auditor who fabricates a
*fully self-consistent* transcript is **not** caught. Heartwood binds the
auditor's protocol, not the provider's speech. Closing this requires a
transport-binding layer — AEX signatures or TLSNotary/zkTLS — and note that
zkTLS today is designated-verifier, so a third party still trusts the notary.

## v0.3 — portability, actually

**v0.2 claimed portable receipts and delivered half of it.** The shuffle was
specified language-independently; **pool generation was still CPython's
Mersenne Twister**. Since a verifier must regenerate the pool both to check the
commitment and to re-grade responses, a Rust or Go verifier still could not
verify a Heartwood receipt. One derivation fixed, both claimed.

Found by auditing the claim rather than trusting it: `grep` for `random` in
`challenges.py` after a clean-clone test.

v0.3 derives every pool item from the same HMAC-SHA256 DRBG
(`randint`/`randrange`/`choice`/`sample`, each specified in `SPEC.md` §4), and
publishes test vectors for **both** derivations. Verification is version-scoped
on both axes:

| receipt version | pool generation | shuffle |
|---|---|---|
| `heartwood/0.1` | CPython MT | CPython MT |
| `heartwood/0.2` | CPython MT | portable |
| `heartwood/0.3` | portable | portable |

All ten previously published receipts still verify. Ground truth re-verified
under the new generator: 5,400 items, 0 bad. Tests **78 → 95**.

Fresh v0.3 audit on Claude Haiku 4.5 (calibration 20/20 → p0 = 0.787):

| endpoint | verdict | queries | rate |
|---|---|---|---|
| honest | NO_EVIDENCE_OF_DEFICIT | 25 | 1.000 |
| **effort-skimmed** | **EFFORT_DEFICIT** | **6** | 0.167 |

One test failed during this change and was correct to fail: the v0.1
compatibility fixture had been building a *portable* pool and merely relabelling
it `v0.1`. It only became detectable once pool generation was version-scoped —
the fixture was never a real v0.1 receipt, so it had been proving nothing.

## v0.2 — portability and scale

Two gaps flagged in v0.1 were addressed.

### Portability (closed)

v0.1 derived the challenge order with Python's `random.Random.shuffle`, which
reproduces only under CPython — so a Rust or Go verifier could not recompute
the order and the receipt was **not actually portable**. A real interop defect
in a protocol whose entire value is that anyone can recheck it.

v0.2 specifies the shuffle exactly: **HMAC-SHA256 in counter mode** as the
random source, **Fisher-Yates** with **rejection sampling** for unbiased index
selection. HMAC-SHA256 is in every standard library, so an independent
implementation needs no crypto dependency — chosen over ChaCha20 for exactly
that reason. Cross-language test vectors ship in `portable.py::test_vectors()`.

Verified unbiased: over 60,000 shuffles of n=5, all 120 permutations appear
with observed stdev **21.8** against a theoretical **22.3** for a uniform
distribution. Plain modulo (the common shortcut) fails this test.

Because this changes a derivation, **verification is version-scoped**: all
three v0.1 receipts in `evidence/` still verify under v0.2 code. A protocol
that cannot verify its own history is not a protocol.

### Independent replications (closed)

A single audit firing at query 31 is an anecdote. Eight independent audits —
each with its own pool seed, so a different committed pool and a different
beacon-derived order — give a distribution:

| arm | n | result |
|---|---|---|
| effort-skimmed | 5 | **5/5 detected** — fired at queries **23, 26, 28, 28, 34** (median **28**) |
| honest | 3 | **0/3 false positives** — peak evidence 10^−0.07, 10^+0.10, 10^−0.17 |

The Monte Carlo model predicted a median of **28** and p90 of **42** for full
skim. Observed median: **28**, max 34. Theory and practice agree without
tuning.

One honest replication scored **0.489** — barely above the null boundary
`p0 = 0.446`, an unlucky honest run. Its evidence crept to 10^+0.10 and came
nowhere near the 10² threshold. That is the stress case for a false positive,
and the supermartingale held.

### Frontier scale (closed — run on a production API)

Run against **Claude Haiku 4.5 through the production Anthropic Messages API**.
Same model, same weights, same signed response on both arms; only the serving
configuration differs.

**A measured correction first.** The adapter's original hollow mode disabled
extended thinking and capped output at 300 tokens. It produced **no separation
at all** — honest and hollow both scored 1.00 across tiers 3–5. The reason is
worth stating plainly:

> Disabling `thinking` is not an effort skim. With room to generate, the model
> simply reasons in the **visible** response instead — measured at 110–252
> output tokens and identical accuracy. That is a display change, not a
> compute change.

**Effort is tokens generated, wherever they appear.** A provider actually
skimming compute suppresses deliberation everywhere, so the corrected hollow
mode does all three — thinking disabled, a provider-injected system prompt
forbidding working, and a tight output cap. All three are invisible to the
customer, whose own prompt is transmitted unchanged.

**The capability cliff on a frontier model** (12 items per cell):

| tier | honest | skimmed | separation | honest tokens | skimmed tokens |
|---|---|---|---|---|---|
| 2 | 1.00 | 0.42 | +0.58 | 161 | 5 |
| **3** | **1.00** | **0.00** | **+1.00** | **222** | **6** |
| 4 | 1.00 | 0.00 | +1.00 | 340 | 8 |
| 5 | 1.00 | 0.00 | +1.00 | 496 | 6 |

~30× less compute, and accuracy collapses from 100% to 0%.

**Live audit** (difficulty 3, `state_track`, α=0.01, p1=0.30; calibration
30/30 → p0 = 0.847):

| endpoint | verdict | queries | rate | peak evidence | receipt |
|---|---|---|---|---|---|
| honest | NO_EVIDENCE_OF_DEFICIT | 60 | 1.000 | 10^−0.45 | valid ✓ |
| **effort-skimmed** | **EFFORT_DEFICIT** | **4** | 0.000 | 10^+2.64 | valid ✓ |
| **50% dilution** | **EFFORT_DEFICIT** | **14** | 0.429 | 10^+2.58 | valid ✓ |

Over 60 honest queries the evidence decayed monotonically to 10^−27 — no false
positive, and not a close call.

**The sharper the model, the cheaper the audit:**

| | laptop (gemma:2b) | frontier (Haiku 4.5) |
|---|---|---|
| full skim | 31 queries | **4** |
| dilution | 71 queries (ε=0.7) | **14** (ε=0.5) |
| ε=0.5 dilution | **undetectable** | **caught** |

A capable model fails harder when its compute is removed, so each query
carries more evidence. Total cost of the frontier run: a few cents.

**Honest scope of the claim.** This is a real production API, a real frontier
model, and real serving knobs — but the skim was configured by us, not caught
in the wild. It demonstrates that the audit detects the attack, not that any
provider is performing it.

### Claude Opus 5 — and why the cliff is model-relative

Repeated on **Claude Opus 5**, the strongest model tested. Its thinking config
differs (`budget_tokens` is removed and returns a 400; thinking is on by
default; `disabled` is only accepted at effort ≤ high), so the adapter selects
per model.

The headline finding is methodological:

| tier | Haiku 4.5 | Opus 5 |
|---|---|---|
| 3 | honest 1.00 / skimmed **0.00** — cliff | honest 1.00 / skimmed **1.00** — *no evidence* |
| 5 | — | honest 1.00 / skimmed **0.00** — cliff |

**Opus 5 solves an 8-step chain in 3 output tokens with no deliberation.** Audit
it with Haiku's tier and every query is uninformative. The capability band is
not a property of the protocol; it is a property of the *claimed model*, and
calibration is what finds it. This is the single most important operational
lesson in the whole project.

**Live audit** (difficulty 5, α=0.01; calibration 20/20 → p0 = 0.787):

| endpoint | declared p1 | verdict | queries | rate | evidence |
|---|---|---|---|---|---|
| honest | 0.30 | NO_EVIDENCE_OF_DEFICIT | 45 | 0.978 | 10^−0.42 |
| **full skim** | 0.30 | **EFFORT_DEFICIT** | **4** | 0.000 | 10^+2.07 |
| 50% dilution | 0.30 | not caught | 45 | 0.600 | 10^+0.49 |
| **50% dilution** | **0.65** | **EFFORT_DEFICIT** | **33** | 0.515 | 10^+2.04 |

The dilution rows are the interesting pair, and we publish both. The realized
mix landed at 0.600 correct — **milder than the declared tolerance of 0.30** —
so the bet drifted negative and never fired. Re-declaring the tolerance at
`p1 = 0.65` (a separate audit with its own pre-declared plan, not a
continuation) caught the same endpoint in 33 queries.

That is the power/tolerance tradeoff demonstrated rather than asserted:
**the test is only as sensitive as the degradation you declare you care
about.** Declaring a milder tolerance costs queries (4 → 33) and buys
sensitivity. A negative result is therefore never "the endpoint is honest" —
it is "no degradation beyond `p1` was detected in `n` queries."

Note also that `thinking_chars` reads 0 on Opus 5 even on the honest arm:
thinking display defaults to `omitted`, so reasoning happens and is billed but
is not surfaced. **Output tokens, not visible thinking, is the effort proxy.**

## Test suite

`python tests.py` → **121/121 passing**, covering ground-truth re-derivation
(3,350 items across all five families), golden grading cases taken from real
hand-verified payloads, the supermartingale property, empirical type-I control,
log-space overflow, Wilson bounds, commitment binding (questions *and* answers),
beacon determinism and sensitivity, the portable shuffle's unbiasedness,
version-scoped verification, receipt round-trip, and the adversary suite.

`python verify_truth.py` independently re-derives a further **5,400** items
across three families by parsing the rendered question text, using no code
shared with the generator — so a bug in the generator cannot hide itself.

## Bugs found and fixed during development

Recorded because they shaped the design:

1. **Answer-extraction bug.** The model emits `Answer: 16` *first*, then reasons
   correctly to 26. The naive extractor scored a correct answer as wrong. Fixed
   with a priority-based assertion parser; locked in by golden tests.
2. **Ground-truth bug.** `money_chain` used integer division, so $4×3 at 10% off
   yielded truth=11 when the correct answer is $10.80 — penalising a *correct*
   model on 2 of 6 calibration items. Fixed by requiring the discount to divide
   the total exactly; verified by re-deriving 5,400 truths with an independent
   parser.
3. **Float64 overflow.** Wealth grows exponentially and overflowed within a few
   hundred items. Moved to log-space accumulation.
4. **Unverified claim.** We asserted style fingerprinting was weak against
   effort downgrade, then measured AUC 0.941 for a length-only detector against
   the naive skim. The claim was narrowed to the padded attacker and the naive
   result published.
