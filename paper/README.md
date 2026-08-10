# Preprint

`heartwood.tex` — *Heartwood: Publicly Verifiable Proof of Semantic Effort for
Black-Box LLM Endpoints*. ~4,100 words, 16 references, self-contained (no `.bib`,
no custom style files, no external figures).

## Before you submit — one thing you must change

**arXiv requires a real author name.** The paper currently carries the
placeholder `zcashsensei`. arXiv's policy is that submissions are attributed to
real identities; a pseudonym will be flagged during moderation. Replace the
`\author{}` line before submitting, or accept that the submission may be held.

An affiliation is not required for an independent submission, but the name is.

## Building

There is no LaTeX toolchain on the development machine, so the PDF has not been
produced locally. Any of these work:

```bash
pdflatex heartwood.tex && pdflatex heartwood.tex   # twice, for cross-refs
```

- **Overleaf** — upload `heartwood.tex`, compiles as-is.
- **arXiv** — accepts the `.tex` source directly and compiles server-side, which
  is the normal submission path. You do not need to upload a PDF.

Packages used are all in TeX Live: `geometry`, `fontenc`, `lmodern`, `amsmath`,
`amssymb`, `amsthm`, `booktabs`, `url`, `hyperref`, `microtype`.

## Suggested categories

| | |
|---|---|
| Primary | **cs.CR** — Cryptography and Security |
| Cross-list | **cs.LG** — Machine Learning |
| Cross-list | **stat.ME** — Methodology (for the anytime-valid testing) |

The paper sits directly against two cs.CR arXiv preprints (Hollow-LLM
2607.28884, IRIS 2607.20860), so cs.CR is the natural home.

## Checking the paper

```bash
python check_paper.py
```

Two passes:

1. **Structure** — balanced environments and braces, required macros present.
2. **Facts** — every number quoted in the paper is re-read from the receipt it
   came from in `../evidence/`, and compared.

The second pass is the one that matters. A paper is a claim about what was
measured, so no figure in it is trusted: 27 claims are checked against
artefacts, and the script exits non-zero if any disagrees. Re-run it after any
edit to the results sections.

## What the paper deliberately includes

Reviewers reward this, and it is the honest thing to do:

- **Both negative results**, with receipts — the configuration that produced *no*
  separation (disabling a reasoning parameter is not an effort skim), and the
  dilution that went undetected because it was milder than the declared
  tolerance.
- **The fabrication attack** the protocol does *not* catch, stated in the threat
  model rather than buried.
- **An explicit disclaimer of novelty** for the statistical machinery.
- **The admission that the skim was configured by us**, not observed in the wild.
