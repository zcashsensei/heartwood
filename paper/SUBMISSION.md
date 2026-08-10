# arXiv submission package

Everything below is ready to paste. The one thing that cannot be automated is
the account: arXiv requires a **registered author**, and first-time submitters
to a category generally need an **endorsement**. Submitting also means
personally accepting an **irrevocable licence to distribute** and asserting
authorship — so the final click has to be yours.

---

## Step 0 — the likely blocker: endorsement

If you have never submitted to `cs.CR`, arXiv will ask for an endorsement
before accepting the paper. This is the step to start first, because it depends
on someone else.

**How it works.** After registering and starting a submission, arXiv generates
an endorsement code and shows you the request URL. You send that code to
somebody who has already published in `cs.CR`; they click a link and confirm.
They are vouching that the work is plausibly topical, **not** peer-reviewing it.

**Who to ask.** The two author groups you are already writing to are the
obvious candidates — both published in `cs.CR` this year, and both have a
direct interest in the paper because it engages their results:

- Chen Gong, Beijie Liu, Mengyuan Li (arXiv:2607.28884)
- Yuewei Zhang, Zhi-Hai Zhang, Hanzhang Qin (arXiv:2607.20860)

If you are emailing them anyway, ask in that same message rather than sending
a second one. One added sentence is enough:

> If the work looks topical to you, I would also be grateful for an arXiv
> endorsement for cs.CR — I am unaffiliated and this would be my first
> submission to that archive. My endorsement code is XXXXXX. No obligation at
> all if you would rather not.

Put it **at the end**, after the substantive question. The paper should be the
reason you are writing; the endorsement is a favour attached to it.

---

## Step 1 — files

arXiv accepts a single `.tex` file. Upload **`heartwood.tex`** directly. There
is no `.bib`, no figures, and no custom class file, so nothing else is needed.
Do not upload a PDF you compiled yourself — arXiv compiles from source, and a
self-made PDF is rejected for TeX submissions.

Packages used are all standard TeX Live: `geometry`, `fontenc`, `lmodern`,
`amsmath`, `amssymb`, `amsthm`, `booktabs`, `url`, `hyperref`, `microtype`.

---

## Step 2 — metadata (paste these verbatim)

**Title**

```
Heartwood: Publicly Verifiable Proof of Semantic Effort for Black-Box LLM Endpoints
```

**Authors**

```
George Tejada
```

**Abstract** — plain text, LaTeX math stripped, since the metadata field is not
rendered:

```
A customer calling a hosted language model cannot tell how much computation the
provider actually spent on their request. Existing verification layers each bind
a different object and none binds effort: trusted-execution attestation binds the
hardware and the loaded image, zero-knowledge proofs of inference bind the
architecture and committed weights, and signed-response provenance binds a
signature chain. The Hollow-LLM attack establishes that this is not an
engineering gap but a structural one -- "proof of correct inference is not proof
of large-model execution" -- because a prover can satisfy the circuit while
collapsing the effective computation. Behavioural auditing does measure
capability, but the state of the art states its own limitation plainly: such
audits are auditor-centric, with no mechanism for independent verification and no
use of cryptographic commitment or public randomness.

We close the gap between these two literatures. Our observation is that a correct
answer to a problem requiring N sequential steps is itself evidence that N steps
were spent: effort can be bound semantically, in the output, where cryptography
provably cannot bind it in the computation. We make that evidence transferable by
committing a challenge pool before a public randomness beacon selects which items
are used, and by accumulating evidence as an anytime-valid test supermartingale,
so neither cherry-picking nor optional stopping can bias the result. The output
is a receipt that any third party recomputes offline, with no contact with the
auditor or the provider and no cooperation from the provider at any point.

On production frontier APIs, Heartwood detects a full effort skim on Claude
Opus 5 in 4 queries and on Claude Haiku 4.5 in 4 queries at alpha = 0.01, with no
false positive across 105 honest queries. We report a property we did not
anticipate: the audit becomes cheaper on more capable models, from 31 queries on
a 2B local model to 4 on frontier models, because a capable model fails harder
when its compute is removed. We also report two negative results that constrain
the method -- disabling a reasoning parameter is not by itself an effort skim,
and a degradation milder than the declared tolerance is not detected -- and we
publish the receipts for both.
```

**Comments**

```
16 pages. Reference implementation, protocol specification, cross-language test
vectors, and all evaluation receipts (including both negative results) are
MIT-licensed at https://github.com/zcashsensei/heartwood
```

**Categories**

| Field | Value |
|---|---|
| Primary | `cs.CR` — Cryptography and Security |
| Cross-list | `cs.LG` — Machine Learning |
| Cross-list | `stat.ME` — Methodology |

`cs.CR` is right: the paper sits directly against two `cs.CR` preprints and its
subject is verification under an adversarial provider.

**ACM class** (optional)

```
K.6.5; I.2.7; G.3
```

---

## Step 3 — licence

Recommended: **CC BY 4.0**.

It matches the MIT licence on the code — permissive, reuse allowed with
attribution — and it is the option most compatible with a paper whose whole
argument is that the evidence should be independently checkable. The default
arXiv minimal licence would also work but permits less downstream reuse.

Whichever you pick, note that the grant to arXiv is **irrevocable**. You cannot
un-publish a preprint; you can only submit a revised version. Be sure the
author name is what you want permanently attached before you click submit.

---

## Step 4 — timing

Submissions received by **14:00 US Eastern, Mon–Fri** are typically announced at
**20:00 Eastern the same day**. Everything passes through moderation, which can
add delay, particularly for an unaffiliated first-time submitter.

---

## Step 5 — after it is live

1. Add the arXiv ID to `README.md`, `CITATION.cff`, and `docs/index.html`.
2. Add the ID to both outreach emails before sending — a cold email from an
   unaffiliated researcher reads very differently with an arXiv ID attached.
3. Consider a GitHub release tagged to the announced version so the code and the
   paper have a matching citable snapshot.

---

## Pre-flight check

Run before uploading. It re-reads every figure quoted in the paper from the
receipt it came from, and checks the LaTeX structure:

```bash
python paper/check_paper.py
```

27 factual claims, all currently matching. Re-run after any edit.
