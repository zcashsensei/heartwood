"""Independently re-derive every ground truth by parsing the question text.

The generator and the checker must not share code paths -- a bug in the
generator would otherwise be invisible. This parser reads only the rendered
English question, exactly as the model sees it.
"""
import re

import challenges as C

bad = n = 0
for diff in (0, 1, 2, 3):
    for it in C.make_pool(999, 400, diff, ["money_chain"]):
        m = re.search(r"costs \$(\d+) and I buy (\d+).*?A (\d+)%", it["q"])
        p, q, d = map(int, m.groups())
        exact = p * q * (100 - d) / 100.0
        n += 1
        if abs(exact - float(it["a"])) > 1e-9:
            bad += 1
            if bad < 4:
                print("  MISMATCH:", it["q"][:74], "| truth", it["a"],
                      "| exact", exact)
print(f"money_chain : {n-bad}/{n} exact, {bad} bad")

bad2 = n2 = 0
for diff in (0, 1, 2, 3):
    for it in C.make_pool(999, 300, diff, ["state_track"]):
        m = re.match(r"Start with the number (\d+), then (.+)\. What", it["q"])
        cur = int(m.group(1))
        for op in m.group(2).split(", then "):
            if op.startswith("add"):
                cur += int(op.split()[1])
            elif op.startswith("subtract"):
                cur -= int(op.split()[1])
            else:
                cur *= int(op.split()[-1])
        n2 += 1
        if str(cur) != it["a"]:
            bad2 += 1
            if bad2 < 4:
                print("  MISMATCH:", it["q"][:74], "| truth", it["a"],
                      "| exact", cur)
print(f"state_track : {n2-bad2}/{n2} exact, {bad2} bad")

bad3 = n3 = 0
DAYS = C.DAYS
for diff in (0, 1, 2, 3):
    for it in C.make_pool(999, 200, diff, ["date_offset"]):
        m = re.match(r"If today is (\w+), what day of the week is it (\d+)",
                     it["q"])
        d0, off = DAYS.index(m.group(1)), int(m.group(2))
        n3 += 1
        if DAYS[(d0 + off) % 7] != it["a"]:
            bad3 += 1
print(f"date_offset : {n3-bad3}/{n3} exact, {bad3} bad")
