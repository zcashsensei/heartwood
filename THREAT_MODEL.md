# Why another layer? The attack that defeats all four existing ones

Existing verification layers each bind a different object. None of them binds
**computational effort per request**.

| Layer | Binds | Representative work |
|---|---|---|
| TEE attestation | hardware, firmware, binary image, loaded weights | NVIDIA CC-mode, Intel TDX / AMD SEV-SNP, Apple PCC, Tinfoil, Phala, Azure confidential inferencing |
| zkML / proof-of-inference | output consistent with declared architecture + committed weights | zkLLM, NANOZK, DeepProve, CommitLLM, SVIP |
| Transport / provenance attestation | a signature chain over request ↔ response | AEX, Evidence-Bound Gateway-Path Provenance, TLSNotary / zkTLS |
| Behavioural auditing | the served model's output distribution | LLMmap, RUT, IRIS, "Are You Getting What You Pay For?" |

## The gap, stated by the field itself

**Hollow-LLM** (arXiv 2607.28884, Jul 2026) proved the cryptographic layers
cannot close it:

> "proof of correct inference is not proof of large-model execution"

A provider can declare a large architecture, commit to ghost weights that embed
a small model, execute only the small model, and still satisfy the ZK verifier.
The authors call this the **effort gap** and note that TEEs "provide stronger
guarantees but sacrifice public verifiability."

**IRIS** (arXiv 2607.20860, Jul 2026), the state of the art in behavioural
auditing, names the remaining hole as its own limitation:

> "Third-party verification: No mechanism allows independent verification; the
> audit is auditor-centric."
> "No cryptographic commitment or public randomness is used; the audit relies
> on the auditor's honesty about the frozen budget."

So: the cryptographic layers are publicly verifiable but semantically empty on
effort. The behavioural layer is semantically real but **non-transferable** —
you can convince yourself, but you cannot convince anyone else.

## The attack Heartwood targets

**Silent reasoning-effort downgrade.** The provider serves the genuine model,
genuine weights, genuine binary — but spends less computation per request
(reduced reasoning budget, truncated chain-of-thought, lowered effort tier).

This is not hypothetical. Reasoning tokens are documented as silently dropped by
some models routed through gateways, and GPT-5.1 defaults `reasoning_effort` to
`none`, so code that reasoned last month can silently stop.

Trace it through every layer:

| Layer | Verdict on this attack | Why |
|---|---|---|
| TEE attestation | **PASSES** | identical image, identical weights loaded |
| zkML weight commitment | **PASSES** | weights are genuinely the committed ones |
| AEX / zkTLS provenance | **PASSES** | provider signs an honest response it really produced |
| Style fingerprinting (LLMmap/IRIS) | **depends on the attacker** — see below | same model, same stylistic signature |
| **Heartwood** | **CATCHES IT** | capability is a function of effort, and cannot be faked downward-free |

### Style detection: measured, not assumed

We initially asserted that style fingerprinting is weak against effort
downgrade. **That assertion was wrong for a naive attacker and we measured it:**
a response-**length**-only classifier separates our short-output hollow endpoint
from the honest one with **AUC 0.941**. A crude skim is easy to catch.

So the honest claim is narrower and more useful: the attack that matters is the
*padded* one, where the provider commits to an answer before deliberating and
then emits a fluent post-hoc justification of normal length.

**Measured, both attacker strengths:**

| attacker | style detector (length) | capability gap |
|---|---|---|
| naive skim (short answers) | AUC **0.941** — caught by style alone | +0.75 |
| **padded skim (realistic)** | AUC **0.523** — **blind** | **+0.542** |

Against the padded attacker, honest accuracy is 0.750 and skimmed accuracy is
0.208, while a length classifier performs at chance. **Style is cheap to fake;
capability is not.** That asymmetry is the entire reason a capability test binds
effort where cryptography cannot.

## Why capability, not style

Style mimicry is cheap: an adversarial provider aware of a fingerprint probe can
tune a substitute to reproduce surface statistics. **Capability is not cheap.**
A model that does not spend the computation cannot produce the answer to a
problem that requires it. Binding the audit to *task success at the capability
cliff* makes evasion require actually doing the work — which is precisely the
outcome the customer is paying for.

This is the semantic counterpart to the effort gap: cryptography cannot bind
effort, but **a correct answer to a problem that requires N steps is itself
evidence that N steps were taken.**

## Incentive compatibility: detection is not the only win

A provider might try to defeat the audit by spending full effort on any request
that *looks* like it needs reasoning. Note what that costs them: the requests
that look like they need reasoning are exactly the requests where reasoning is
what the customer is paying for. **The provider's best response to being
auditable is to actually do the work where the work matters.**

This matters because it weakens the usual objection to behavioural audits —
"an adaptive provider will just detect your probes." Here, probe detection does
not buy the adversary much. Their options are:

| Provider strategy | Outcome |
|---|---|
| Skim effort everywhere | caught fast (median 7 queries at α=0.01) |
| Skim only on requests that look easy | customer gets full effort on hard requests — the ones they care about |
| Spend full effort on everything | no skim, which is the honest service |

The residual attack is selective full-effort on *audit-shaped* traffic
specifically, which is why challenge indistinguishability still matters — see
limitation 7.

## What Heartwood does NOT prove

Stated plainly, because a grant reviewer will find these anyway:

1. **It does not bind responses to the provider.** A dishonest *auditor* could
   fabricate a transcript. Heartwood composes with AEX or zkTLS for that leg:
   AEX proves "the provider really said this"; Heartwood proves "what was said
   required the compute." Note zkTLS today is designated-verifier — convincing
   a third party still means trusting the notary.
2. **Offline verification cannot establish that the beacon was ever drawn.**
   This is the sharpest limit in the list and it was found by attacking our own
   verifier, so the numbers are measured rather than estimated.

   `verify_receipt()` derives the item order from the beacon *the receipt
   itself carries*. That establishes self-consistency, not that the value came
   from drand. An auditor free to invent the beacon therefore chooses the
   sample — which is precisely what the commit→beacon ordering exists to
   prevent, and it voids the anytime-valid guarantee, because grinding
   candidate beacons **is** peeking.

   Measured against a 300-item pool and an endpoint whose true success rate
   (0.75) sits *above* `p0` (0.70), so there is no deficit to find:

   | beacon | evidence reached | verdict |
   |---|---|---|
   | uncontrolled | 10^−57.4 | no deficit, correctly |
   | ground, after **1,017 tries (0.4 s)** | fires at query **6** | `EFFORT_DEFICIT`, falsely |

   The ground receipt passes all seven offline checks. Declared α was 0.01;
   under a grinding auditor the true false-positive rate approaches 1.

   **Mitigation, and its limits.** `verify_beacon_online()` fetches the named
   round and compares — it rejects the ground receipt and confirms all twelve
   published ones. `verify.py --online` runs it. But this needs the network,
   so a purely offline verifier can only ever report *self-consistency*: the
   CLI now says so in as many words instead of printing a bare `VALID: True`.
   Closing it offline requires carrying drand's BLS signature in the receipt
   and verifying it against the chain public key. That is the right fix and it
   is not yet implemented.

   A reproduction is committed: `python security_test.py`.
3. **It cannot detect a substitution that is behaviourally equivalent.** If the
   cheaper service answers everything the claimed model answers, no black-box
   test can separate them. We argue this is the correct equivalence class for an
   API customer, but it is a real limit, not a strength to be hidden.
4. **Low dilution fractions need many queries.** Detection of a fraction ε of
   downgraded traffic falls into the ε⁻² regime once ε is small; ε=0.1 was not
   detectable within our budget.
5. **The pool must be calibrated per claimed model.** Items the claimed model
   cannot solve carry no evidence, because they fail under honest and hollowed
   serving alike.
6. **The statistical machinery is not novel.** Betting martingales and e-values
   are standard (Ramdas et al.), and anytime-valid testing has been applied to
   API auditing before. The contribution is the *composition* and the *threat
   model*, not the test.
7. **Indistinguishability is argued, not proven.** Our challenges are ordinary
   arithmetic word problems — a real and common category of API traffic — but a
   provider profiling one customer's traffic distribution could still notice a
   shift. The principled fix is to generate capability-cliff items *in the
   customer's own domain and register*, so audit traffic is drawn from the same
   distribution as real traffic. That is future work, not a solved problem.
8. **Power is tied to the declared tolerance.** The Kelly bet is optimal against
   `p1`, so the test is strong against degradation to roughly `p1` or worse and
   weak against milder degradation. Detecting a small dilution fraction requires
   declaring a higher `p1` and paying substantially more queries.
