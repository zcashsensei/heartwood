"""Two endpoint modes over IDENTICAL weights.

This is the whole point of the experiment. Both modes serve the same model
file, same binary, same hardware. A TEE attestation, a zkML weight
commitment, and an AEX response signature are all *identical* between them.
The only difference is how much computation is spent per request.

  honest  -- full reasoning budget (what the customer pays for)
  hollow  -- reasoning suppressed and token budget clipped (effort skimming)
"""
import json
import re
import urllib.request

OLLAMA = "http://localhost:11434/api/generate"
MODEL = "gemma:2b"

HONEST_SUFFIX = (
    "\n\nWork through this step by step, then give your final answer on a new "
    "line in the exact form:\nANSWER: <answer>"
)
HOLLOW_SUFFIX = (
    "\n\nRespond immediately with only the final answer, no working, in the "
    "exact form:\nANSWER: <answer>"
)

# The naive skim (short output) is trivially caught by a length detector --
# measured AUC 0.941 on our corpus. A competent adversary pads. PADDED_SUFFIX
# is the realistic attack: commit to an answer BEFORE deliberating, then emit a
# fluent post-hoc justification so the response looks normal. The computation
# is skipped; only the appearance of work survives.
PADDED_SUFFIX = (
    "\n\nBegin your reply by stating the final answer immediately on the first "
    "line in the form:\nANSWER: <answer>\nThen write a short, confident, "
    "well-formatted explanation of your reasoning for the reader."
)

MODES = {
    "honest": {"suffix": HONEST_SUFFIX, "num_predict": 400},
    "hollow": {"suffix": HOLLOW_SUFFIX, "num_predict": 24},
    "padded": {"suffix": PADDED_SUFFIX, "num_predict": 400},
}


def query(question: str, mode: str, temperature: float = 0.7, seed=None):
    cfg = MODES[mode]
    opts = {"temperature": temperature, "num_predict": cfg["num_predict"]}
    if seed is not None:
        opts["seed"] = seed
    payload = {
        "model": MODEL,
        "prompt": question + cfg["suffix"],
        "stream": False,
        "options": opts,
    }
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    return d.get("response", ""), d.get("eval_count") or 0


_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

# The model asserts its answer in a handful of stereotyped ways. Grading must
# follow the ASSERTION, not merely the presence of the right token: this model
# frequently answers "orbit" and then mentions "anchor" (the true answer) later
# in its explanation. A naive last-occurrence or substring rule scores that
# wrong answer as correct, which would silently corrupt the calibration.
_ASSERT = re.compile(
    r"(?:final\s+answer|the\s+answer|answer)\s*(?:is|:|=)\s*"
    r"[\s*_\"'`$]*([A-Za-z0-9][A-Za-z0-9,.$ ]*)",
    flags=re.I,
)


def extract(text: str) -> str:
    """Pull the CLAIMED answer out of a free-form response.

    Priority 1: the last explicit assertion ("the final answer is X").
    Priority 2: the trailing fragment, from which grade() takes the last
                number / candidate word.
    """
    hits = _ASSERT.findall(text or "")
    if hits:
        return hits[-1].strip().strip("*_`.,!\"' ")
    return (text or "").strip()


def grade(claim: str, truth: str, full_text: str = "") -> int:
    """1 if the response asserts the correct answer, else 0."""
    c, t = (claim or "").lower().strip(), truth.lower().strip()
    if t.lstrip("-").isdigit():
        nums = [n.replace(",", "").rstrip(".") for n in _NUM.findall(c)]
        if not nums:  # no assertion parsed: fall back to the last number seen
            nums = [n.replace(",", "").rstrip(".")
                    for n in _NUM.findall((full_text or "").lower())]
        return int(bool(nums) and nums[-1] == t)
    # Word answer: the asserted span must name the truth word.
    if re.search(rf"\b{re.escape(t)}\b", c):
        return 1
    if not hits_any_word(c) and full_text:
        # No word asserted in the span -- fall back to last candidate word.
        return int(_last_word(full_text.lower()) == t)
    return 0


_CANDIDATES = ["river", "candle", "orbit", "meadow", "anchor", "puzzle",
               "lantern", "harvest", "marble", "thunder", "willow", "compass",
               "ember", "gravel", "monday", "tuesday", "wednesday", "thursday",
               "friday", "saturday", "sunday"]


def hits_any_word(s: str) -> bool:
    return any(re.search(rf"\b{w}\b", s) for w in _CANDIDATES)


def _last_word(s: str):
    best, pos = None, -1
    for w in _CANDIDATES:
        for m in re.finditer(rf"\b{w}\b", s):
            if m.start() > pos:
                best, pos = w, m.start()
    return best
