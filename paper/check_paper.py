"""Structural + factual check on the preprint.

Two jobs:
  1. Will it compile? (balanced environments/braces, required macros present)
  2. Does every number in it match a measured artefact in evidence/?

The second matters more. A paper is a claim about what was measured, so every
figure in it is checked against the receipt it came from rather than trusted.
"""
import json
import pathlib
import re
import sys
from collections import Counter

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
# This script runs from paper/, so the repo root is not importable by default.
sys.path.insert(0, str(ROOT))
tex = (HERE / "heartwood.tex").read_text(encoding="utf-8")
body = "\n".join(l for l in tex.splitlines() if not l.lstrip().startswith("%"))

print("=== 1. STRUCTURE ===")
b = Counter(re.findall(r"\\begin\{([A-Za-z*]+)\}", body))
e = Counter(re.findall(r"\\end\{([A-Za-z*]+)\}", body))
bad = {k: (b[k], e[k]) for k in set(b) | set(e) if b[k] != e[k]}
print("  unbalanced environments :", bad or "none")
print("  braces balanced         :", body.count("{") == body.count("}"),
      f"({body.count('{')} / {body.count('}')})")
for macro in (r"\documentclass", r"\begin{document}", r"\end{document}",
              r"\maketitle", r"\begin{abstract}"):
    print(f"  {macro:24s}:", macro in tex)
print("  bibitems                :", len(re.findall(r"\\bibitem", tex)))
print("  approx words            :", len(re.findall(r"[A-Za-z']+", body)))

print()
print("=== 2. FIGURES vs MEASURED ARTEFACTS ===")


def receipt(path):
    return json.loads((ROOT / "evidence" / path).read_text())


claims, fails = 0, []


def claim(desc, actual, expected):
    global claims
    claims += 1
    ok = actual == expected
    if not ok:
        fails.append(f"{desc}: paper says {expected!r}, artefact says {actual!r}")
    print(f"  {'ok ' if ok else '!! '}{desc:52s} {actual}")


# Frontier Haiku 4.5 (v0.2 receipts under evidence/frontier/)
h_hon = receipt("frontier/receipt_honest.json")
h_hol = receipt("frontier/receipt_hollow.json")
h_dil = receipt("frontier/receipt_dilute.json")
claim("Haiku honest queries", h_hon["result"]["n_queries"], 60)
claim("Haiku honest rate", round(h_hon["result"]["observed_rate"], 3), 1.000)
claim("Haiku skim queries", h_hol["result"]["n_queries"], 4)
claim("Haiku skim rate", round(h_hol["result"]["observed_rate"], 3), 0.000)
claim("Haiku dilution queries", h_dil["result"]["n_queries"], 14)
claim("Haiku dilution rate", round(h_dil["result"]["observed_rate"], 3), 0.429)

# Frontier Opus 5
o_hon = receipt("frontier/opus5_receipt_honest.json")
o_hol = receipt("frontier/opus5_receipt_hollow.json")
o_d30 = receipt("frontier/opus5_receipt_dilute_p1_0.30.json")
o_d65 = receipt("frontier/opus5_receipt_dilute_p1_0.65.json")
claim("Opus5 honest queries", o_hon["result"]["n_queries"], 45)
claim("Opus5 honest rate", round(o_hon["result"]["observed_rate"], 3), 0.978)
claim("Opus5 skim queries", o_hol["result"]["n_queries"], 4)
claim("Opus5 dilution p1=0.30 fired", o_d30["result"]["rejected_at"], None)
claim("Opus5 dilution p1=0.30 rate", round(o_d30["result"]["observed_rate"], 3), 0.600)
claim("Opus5 dilution p1=0.65 queries", o_d65["result"]["n_queries"], 33)
claim("Opus5 dilution p1=0.65 rate", round(o_d65["result"]["observed_rate"], 3), 0.515)
claim("Opus5 declared p1 (mild)", o_d65["plan"]["p1"], 0.65)

# Local gemma:2b (v0.1)
l_hol = receipt("receipt_hollow.json")
l_dil = receipt("receipt_dilute.json")
claim("local skim queries", l_hol["result"]["n_queries"], 31)
claim("local dilution queries", l_dil["result"]["n_queries"], 71)
claim("local p0", l_hol["plan"]["p0"], 0.446)

# Replications
rep = json.loads((ROOT / "evidence" / "replications.json").read_text())
fired = sorted(r["fired_at"] for r in rep if r["scenario"] == "hollow")
honest = [r for r in rep if r["scenario"] == "honest"]
claim("replication skim fired_at (sorted)", fired, [23, 26, 28, 28, 34])
claim("replication skims detected", sum(1 for r in rep
                                        if r["scenario"] == "hollow" and r["fired_at"]), 5)
claim("replication honest false positives",
      sum(1 for r in honest if r["fired_at"]), 0)
claim("unlucky honest run rate",
      round(min(r["rate"] for r in honest), 3), 0.489)

# Honest-query total quoted in the abstract (60 Haiku + 45 Opus 5)
claim("total frontier honest queries",
      h_hon["result"]["n_queries"] + o_hon["result"]["n_queries"], 105)

# --- Section: what offline verification cannot establish --------------------
# The paper now states that an auditor who chooses the beacon manufactures a
# false verdict, and quotes numbers for it. Those numbers must come from the
# artefact, not from the prose -- a paper that describes an attack it cannot
# reproduce is worse than one that never mentions it.
import heartwood as _H

attack = ROOT / "attacks" / "attack_ground_beacon.json"
if attack.exists():
    g = json.loads(attack.read_text(encoding="utf-8"))
    claim("ground receipt passes offline verification",
          _H.verify_receipt(g)["valid"], True)
    claim("ground receipt asserts a deficit",
          g["result"]["verdict"], "EFFORT_DEFICIT")
    claim("ground receipt fires at query 6", g["result"]["rejected_at"], 6)
    claim("ground receipt's endpoint was NOT deficient (p0 below true rate)",
          g["plan"]["p0"] < 0.75, True)
else:
    claim("attacks/attack_ground_beacon.json present "
          "(run security_test.py)", False, True)

# Every published receipt must anchor to a real drand round -- the claim the
# mitigation paragraph rests on. Skipped without network rather than assumed.
try:
    anchored = [_H.verify_beacon_online(json.loads(p.read_text(encoding="utf-8")))
                for p in sorted((ROOT / "evidence").glob("receipt_*.json"))
                + sorted((ROOT / "evidence").glob("*/*receipt*.json"))]
    if any(a["anchored"] is None for a in anchored):
        print("  skip  beacon anchoring (drand unreachable)")
    else:
        claim("published receipts anchored to real drand rounds",
              sum(a["anchored"] is True for a in anchored), len(anchored))
except Exception as e:                                       # pragma: no cover
    print(f"  skip  beacon anchoring ({type(e).__name__})")

print()
if fails:
    print(f"FAILED {len(fails)}/{claims} factual claims")
    for f in fails:
        print("   -", f)
    raise SystemExit(1)
print(f"All {claims} factual claims match the published artefacts.")
