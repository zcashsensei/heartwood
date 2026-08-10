"""Fail if any count stated in the docs disagrees with reality.

Numbers in prose drift every time the code grows: this repo shipped "60/60
tests" and "3,600 ground truths" in three files after both figures had changed.
Nobody notices, because a stale number looks exactly like a fresh one.

So the counts are COMPUTED here and the docs are checked against them. Run it
before publishing anything.
"""
import glob
import json
import pathlib
import re
import subprocess
import sys

import challenges as C
import heartwood as H

ROOT = pathlib.Path(__file__).parent
fails = []


def computed():
    """Ground truth, derived — never typed."""
    out = {}

    r = subprocess.run([sys.executable, "tests.py"], capture_output=True,
                       text=True, cwd=ROOT)
    m = re.search(r"PASSED (\d+)/(\d+)", r.stdout)
    out["tests"] = f"{m.group(1)}/{m.group(2)}" if m else "UNKNOWN"

    files = sorted(glob.glob(str(ROOT / "evidence/receipt_*.json"))
                   + glob.glob(str(ROOT / "evidence/*/*receipt*.json")))
    ok = sum(H.verify_receipt(json.load(open(f)))["valid"] for f in files)
    out["receipts"] = f"{ok}/{len(files)}"

    # what verify_truth.py independently re-derives
    out["verify_truth"] = sum(
        len(C.make_pool(999, n, d, [fam]))
        for fam, n in (("money_chain", 400), ("state_track", 300), ("date_offset", 200))
        for d in range(6)
    )

    # what tests.py re-derives inline
    out["tests_truth"] = sum(
        len(C.make_pool(4242, n, d, [fam]))
        for fam, tiers, n in (("money_chain", (0, 1, 2, 3), 250),
                              ("state_track", (0, 1, 2, 3), 250),
                              ("date_offset", (0, 1, 2, 3), 150),
                              ("word_index", (1,), 150),
                              ("set_logic", (0, 1, 2, 3), 150))
        for d in tiers
    )

    r = subprocess.run([sys.executable, "paper/check_paper.py"], capture_output=True,
                       text=True, cwd=ROOT)
    m = re.search(r"All (\d+) factual claims", r.stdout)
    out["paper_claims"] = m.group(1) if m else "UNKNOWN"

    out["version"] = H.VERSION.split("/")[-1]
    return out


def check(label, ok, detail=""):
    print(f"  {'ok ' if ok else '!! '}{label:44s} {detail}")
    if not ok:
        fails.append(label)


def main():
    c = computed()
    print("computed from the code:")
    for k, v in c.items():
        print(f"    {k:14s} {v}")
    print("\ndocs agree?")

    # Key by path relative to the repo, not by bare filename: paper/README.md
    # and ./README.md share a name and one silently overwrote the other, so the
    # root README was never actually checked.
    docs = {str(p.relative_to(ROOT)).replace("\\", "/"): p.read_text(encoding="utf-8")
            for p in list(ROOT.glob("*.md")) + [ROOT / "docs/index.html"]
            + list((ROOT / "paper").glob("*.md"))}

    # Any "N/N tests|passing" in prose must be the real figure. Tolerate the
    # markdown emphasis that usually wraps these numbers (**95/95** passing).
    pat = re.compile(r"(\d+)\s*/\s*(\d+)\**\s*(?:tests?|passing)")
    for name, text in docs.items():
        for m in pat.finditer(text):
            got = f"{m.group(1)}/{m.group(2)}"
            check(f"{name}: test count {got}", got == c["tests"],
                  "" if got == c["tests"] else f"expected {c['tests']}")

    # Ground-truth totals quoted anywhere must be one of the two real totals.
    valid = {f"{c['verify_truth']:,}", str(c["verify_truth"]),
             f"{c['tests_truth']:,}", str(c["tests_truth"])}
    quoted = re.compile(r"([\d,]{3,})\s+(?:ground[- ]truths?|truths|items)")
    for name, text in docs.items():
        for m in quoted.finditer(text):
            n = m.group(1)
            check(f"{name}: ground-truth count {n}", n in valid,
                  "" if n in valid else f"expected one of {sorted(valid)}")

    # Version: only check the places that assert "this is the CURRENT version".
    # RESULTS.md and SPEC.md legitimately name 0.1 and 0.2 when documenting
    # version history and the version-scoping table — flagging those would be a
    # false alarm, and a checker that cries wolf gets ignored.
    current_version_claims = {
        "README.md":   r"spec-heartwood%2F(\d+\.\d+)",       # badge
        "docs/index.html": r"MIT · v(\d+\.\d+)",             # site subtitle
    }
    for name, pattern in current_version_claims.items():
        text = docs.get(name)
        if text is None:
            check(f"{name}: present", False, "file missing")
            continue
        found = re.findall(pattern, text)
        check(f"{name}: current version {found or '—'}",
              bool(found) and all(v == c["version"] for v in found),
              "" if found and all(v == c["version"] for v in found)
              else f"code says {c['version']}")

    check("all receipts verify", c["receipts"].split("/")[0] == c["receipts"].split("/")[1],
          c["receipts"])
    check("paper figures match receipts", c["paper_claims"] != "UNKNOWN",
          f"{c['paper_claims']} claims")

    print()
    if fails:
        print(f"FAILED {len(fails)} check(s) — a stated number disagrees with the code")
        return 1
    print("every stated count matches the code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
