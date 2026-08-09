"""Heartwood test suite. Run: python tests.py

Self-contained (no pytest required). Covers ground truth, grading, the
statistical core, beacon binding, receipt round-trip, and the adversary suite.

The grading tests use GOLDEN CASES taken from real gemma:2b payloads that were
hand-verified during development. They exist because the first grader silently
mis-scored correct answers -- these lock that class of bug out.
"""
import math
import random
import re
import sys

import challenges as C
import endpoint as E
import heartwood as H

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if not cond:
        FAILS.append(f"{name}  {detail}")
        print(f"  FAIL  {name}  {detail}")
    return cond


def section(t):
    print(f"\n== {t}")


# ---------------------------------------------------------------- truth ----
section("ground truth is exact (independent re-derivation from question text)")

bad = n = 0
for diff in (0, 1, 2, 3):
    for it in C.make_pool(4242, 250, diff, ["money_chain"]):
        m = re.search(r"costs \$(\d+) and I buy (\d+).*?A (\d+)%", it["q"])
        p, q, d = map(int, m.groups())
        n += 1
        bad += abs(p * q * (100 - d) / 100.0 - float(it["a"])) > 1e-9
check("money_chain discounts divide exactly", bad == 0, f"{bad}/{n} wrong")

bad = n = 0
for diff in (0, 1, 2, 3):
    for it in C.make_pool(4242, 250, diff, ["state_track"]):
        m = re.match(r"Start with the number (\d+), then (.+)\. What", it["q"])
        cur = int(m.group(1))
        for op in m.group(2).split(", then "):
            if op.startswith("add"):
                cur += int(op.split()[1])
            elif op.startswith("subtract"):
                cur -= int(op.split()[1])
            else:
                cur *= int(op.split()[-1])
        n += 1
        bad += str(cur) != it["a"]
check("state_track arithmetic matches", bad == 0, f"{bad}/{n} wrong")

bad = n = 0
for diff in (0, 1, 2, 3):
    for it in C.make_pool(4242, 150, diff, ["date_offset"]):
        m = re.match(r"If today is (\w+), what day of the week is it (\d+)",
                     it["q"])
        n += 1
        bad += C.DAYS[(C.DAYS.index(m.group(1)) + int(m.group(2))) % 7] != it["a"]
check("date_offset weekday maths", bad == 0, f"{bad}/{n} wrong")

# word_index answer must actually be at the stated position
bad = n = 0
for it in C.make_pool(4242, 150, 1, ["word_index"]):
    m = re.match(r"Consider this list: (.+?)\. Counting from the left "
                 r"starting at 1, what is word number (\d+)", it["q"])
    words = [w.strip() for w in m.group(1).split(",")]
    n += 1
    bad += words[int(m.group(2)) - 1] != it["a"]
check("word_index position matches", bad == 0, f"{bad}/{n} wrong")

# set_logic must never produce a negative or inconsistent count
bad = n = 0
for diff in (0, 1, 2, 3):
    for it in C.make_pool(4242, 150, diff, ["set_logic"]):
        m = re.match(r"In a group of (\d+) people, (\d+) like tea and (\d+) "
                     r"like coffee, and (\d+) like both", it["q"])
        t, a, b, both = map(int, m.groups())
        n += 1
        bad += (t - (a + b - both) != int(it["a"])) or int(it["a"]) < 0
check("set_logic inclusion-exclusion, non-negative", bad == 0, f"{bad}/{n} wrong")


# -------------------------------------------------------------- grading ----
section("grading (golden cases from real hand-verified payloads)")

GOLD = [
    # (response, truth, expected) -- all hand-checked against gemma:2b output
    ("**Step 1:** Add 5 to 11: 11 + 5 = 16\n**Step 2:** Add 5 to 16: 16 + 5 = 21"
     "\n**The final answer is 21.**", "21", 1),
    # asserts 25 up front, then computes 26. The ASSERTION is what is graded.
    ("The answer is 25.\n\n5 + 7 = 12\n12 + 5 = 17\n17 + 9 = 26", "26", 0),
    # names 'orbit', then mentions 'anchor' later. Substring rules fail here.
    ('The answer is "orbit".\n\nLantern, anchor, and compass are all objects '
     'used for navigation.', "anchor", 0),
    # lists "3. Ember" but asserts "2"
    ("The answer is 2.\n\n1. Willow\n2. Puzzle\n3. Ember\n4. Candle\n\n"
     "Therefore, word number 3 is 2.", "ember", 0),
    ("**Step 3**: Subtract the discount: $12 - $6 = $6\n\n"
     "**Therefore, the final total is $6.**", "6", 1),
    ("Therefore, there are **2 people who like neither tea and coffee**.",
     "4", 0),
    ("**ANSWER:** SUNDAY", "Sunday", 1),
    ("Sure, here's how to calculate it:\n**Step 2**: 8 days from Sunday is "
     "Saturday.\nANSWER: <Saturday>", "Monday", 0),
    ("ANSWER: 391", "391", 1),
    ("no idea", "42", 0),
    ("", "42", 0),
]
for i, (resp, truth, want) in enumerate(GOLD):
    got = E.grade(E.extract(resp), truth, resp)
    check(f"golden[{i}] truth={truth!r} -> {want}", got == want, f"got {got}")

# grading must be deterministic and idempotent
r = "**The final answer is 21.**"
check("grading deterministic",
      all(E.grade(E.extract(r), "21", r) == 1 for _ in range(50)))


# ----------------------------------------------------------- statistics ----
section("statistical core")

p0, p1 = 0.80, 0.50
lam = H.kelly_lambda(p0, p1)
check("kelly closed form", abs(lam - (p0 - p1) / (p0 * (1 - p0))) < 1e-12,
      f"lam={lam}")
check("bet keeps wealth strictly positive", lam < 1.0 / (1.0 - p0))
check("kelly is zero when p1 == p0", H.kelly_lambda(0.8, 0.8) == 0.0)
check("kelly never negative (p1 above p0)", H.kelly_lambda(0.8, 0.9) == 0.0)

# supermartingale property: E[e_t] <= 1 under H0 (true rate >= p0)
for true_p in (0.80, 0.85, 0.95):
    ev = true_p * (1 + lam * (p0 - 1)) + (1 - true_p) * (1 + lam * p0)
    check(f"E[e_t] <= 1 at true p={true_p}", ev <= 1 + 1e-12, f"E={ev:.6f}")

# and > 1 growth under a genuine deficit
ev_bad = 0.3 * (1 + lam * (p0 - 1)) + 0.7 * (1 + lam * p0)
check("E[e_t] > 1 under real deficit", ev_bad > 1.0, f"E={ev_bad:.4f}")

# log-space path equals the naive product for short, non-overflowing runs
outs = [1, 0, 1, 1, 0, 0, 1, 0]
path = H.wealth_path(outs, p0, lam)
w = 1.0
for x in outs:
    w *= (1 + lam * (p0 - x))
check("log10 wealth matches direct product",
      abs(path[-1] - math.log10(w)) < 1e-12, f"{path[-1]} vs {math.log10(w)}")

# long runs must not overflow (this was a real bug: float64 cumprod inf)
long_path = H.wealth_path([0] * 5000, p0, lam)
check("no overflow over 5000 items",
      math.isfinite(long_path[-1]) and long_path[-1] > 100,
      f"{long_path[-1]}")

# Wilson lower bound: conservative, monotone, bounded
check("wilson <= point estimate", H.lower_conf_bound(30, 36) < 30 / 36)
check("wilson in [0,1]", 0 <= H.lower_conf_bound(30, 36) <= 1)
check("wilson tightens with n",
      H.lower_conf_bound(300, 360) > H.lower_conf_bound(30, 36))
check("wilson handles n=0", H.lower_conf_bound(0, 0) == 0.0)
check("wilson handles all-success", 0 < H.lower_conf_bound(36, 36) <= 1)

# empirical type-I control: FPR must not exceed alpha
alpha = 0.01
thr = math.log10(1 / alpha)
rng = random.Random(11)
fires = 0
TRIALS = 4000
for _ in range(TRIALS):
    lw = 0.0
    for _ in range(300):
        x = 1 if rng.random() < p0 else 0      # true rate exactly at the null
        lw += math.log10(1 + lam * (p0 - x))
        if lw >= thr:
            fires += 1
            break
fpr = fires / TRIALS
check(f"empirical FPR {fpr:.4f} <= alpha {alpha}", fpr <= alpha * 1.5,
      f"fpr={fpr}")


# ---------------------------------------------------------- commitments ----
section("commitment and beacon binding")

pool = C.make_pool(20260808, 120, 0, ["state_track", "money_chain"])
c1 = C.pool_commitment(pool)
check("commitment is deterministic", c1 == C.pool_commitment(
    C.make_pool(20260808, 120, 0, ["state_track", "money_chain"])))
check("commitment changes with seed",
      c1 != C.pool_commitment(C.make_pool(20260809, 120, 0,
                                          ["state_track", "money_chain"])))
check("commitment changes with families",
      c1 != C.pool_commitment(C.make_pool(20260808, 120, 0, ["state_track"])))
tampered = [dict(it) for it in pool]
tampered[7]["a"] = "999999"
check("commitment binds ANSWERS too",
      c1 != C.pool_commitment(tampered))
tampered2 = [dict(it) for it in pool]
tampered2[7]["q"] = tampered2[7]["q"] + " "
check("commitment binds QUESTIONS too", c1 != C.pool_commitment(tampered2))

b1 = {"randomness": "aa" * 16, "round": 1}
b2 = {"randomness": "bb" * 16, "round": 2}
o1 = H.selection_order(c1, b1, 120)
check("selection deterministic given beacon", o1 == H.selection_order(c1, b1, 120))
check("selection changes with beacon", o1 != H.selection_order(c1, b2, 120))
check("selection changes with commitment",
      o1 != H.selection_order("00" * 32, b1, 120))
check("selection is a permutation", sorted(o1) == list(range(120)))

try:
    C.make_pool(1, 10, 0, ["nope"])
    check("unknown family raises", False, "no exception")
except ValueError:
    check("unknown family raises", True)


# ------------------------------------------------------------- receipts ----
section("receipt round-trip and verification")

beacon = {"chain": "test", "round": 99, "randomness": "cc" * 16,
          "source": "fixture"}
order = H.selection_order(c1, beacon, len(pool))
plan = {"p0": 0.446, "p1": 0.30, "alpha": 0.01,
        "lambda": H.kelly_lambda(0.446, 0.30), "pool_size": 120,
        "max_queries": 60, "families": ["state_track", "money_chain"]}
rng = random.Random(5)
transcript = []
for item_id in order[:40]:
    it = pool[item_id]
    correct = rng.random() < 0.10
    resp = f"ANSWER: {it['a']}" if correct else "ANSWER: 0"
    transcript.append({
        "item_id": item_id, "served_mode": "hollow",
        "question_sha256": H.sha(it["q"]), "response": resp,
        "response_sha256": H.sha(resp),
        "graded": E.grade(E.extract(resp), it["a"], resp)})

rec = H.build_receipt(20260808, 0, c1, beacon, plan, {"n": 36}, transcript,
                      "testhash")
v = H.verify_receipt(rec)
check("valid receipt verifies", v["valid"], str(v["checks"]))
check("all seven checks present", len(v["checks"]) == 7, str(list(v["checks"])))
check("deficit detected on a hollow transcript",
      rec["result"]["verdict"] == "EFFORT_DEFICIT",
      rec["result"]["verdict"])
check("fired index within range",
      1 <= (rec["result"]["rejected_at"] or 0) <= len(transcript))

# an honest transcript must NOT be flagged
honest_t = []
for item_id in order[:40]:
    it = pool[item_id]
    correct = rng.random() < 0.90
    resp = f"ANSWER: {it['a']}" if correct else "ANSWER: 0"
    honest_t.append({
        "item_id": item_id, "served_mode": "honest",
        "question_sha256": H.sha(it["q"]), "response": resp,
        "response_sha256": H.sha(resp),
        "graded": E.grade(E.extract(resp), it["a"], resp)})
rec_h = H.build_receipt(20260808, 0, c1, beacon, plan, {"n": 36}, honest_t,
                        "testhash")
check("honest transcript not flagged",
      rec_h["result"]["verdict"] == "NO_EVIDENCE_OF_DEFICIT",
      rec_h["result"]["verdict"])
check("honest receipt verifies", H.verify_receipt(rec_h)["valid"])


# ------------------------------------------------------------ adversary ----
section("adversary: every in-scope forgery is caught")

import copy


def mutated_is_caught(mut):
    r = copy.deepcopy(rec)
    mut(r)
    return not H.verify_receipt(r)["valid"]


def _flip(r):
    for t in r["transcript"]:
        if t["graded"] == 1:
            t["graded"] = 0
            return
    r["transcript"][0]["graded"] = 1


check("flipped grade caught", mutated_is_caught(_flip))
check("rewritten response caught", mutated_is_caught(
    lambda r: r["transcript"].__setitem__(
        0, {**r["transcript"][0], "response": "ANSWER: 999999"})))
check("dropped items caught", mutated_is_caught(
    lambda r: r.__setitem__("transcript", r["transcript"][:10])))
check("reordered items caught", mutated_is_caught(
    lambda r: r.__setitem__("transcript", list(reversed(r["transcript"])))))
check("swapped beacon caught", mutated_is_caught(
    lambda r: r.__setitem__("beacon", {**r["beacon"], "randomness": "00" * 16})))
check("inflated p0 caught", mutated_is_caught(
    lambda r: r.__setitem__("plan", {**r["plan"], "p0": 0.99})))
check("retuned lambda caught", mutated_is_caught(
    lambda r: r.__setitem__("plan",
                            {**r["plan"], "lambda": r["plan"]["lambda"] * 1.5})))
check("restated verdict caught", mutated_is_caught(
    lambda r: r.__setitem__("result",
                            {**r["result"], "rejected_at": 1,
                             "verdict": "EFFORT_DEFICIT"})))
check("swapped pool caught", mutated_is_caught(
    lambda r: r.__setitem__("pool", {**r["pool"], "seed": 999})))
check("grades all set true caught", mutated_is_caught(
    lambda r: [t.__setitem__("graded", 1) for t in r["transcript"]]))

# Documented boundary: full self-consistent fabrication is NOT caught.
fab = copy.deepcopy(rec)
by_id = {it["id"]: it for it in pool}
for t in fab["transcript"]:
    wrong = "ANSWER: 0" if by_id[t["item_id"]]["a"] != "0" else "ANSWER: 1"
    t["response"], t["response_sha256"], t["graded"] = wrong, H.sha(wrong), 0
fab["result"] = H.build_receipt(20260808, 0, c1, beacon, plan, {"n": 36},
                                fab["transcript"], "testhash")["result"]
check("KNOWN BOUNDARY: fabrication verifies (needs AEX/zkTLS)",
      H.verify_receipt(fab)["valid"],
      "if this now FAILS, the boundary changed -- update THREAT_MODEL.md")


# ------------------------------------------------------- portability v0.2 ----
section("portable selection (v0.2): language-independent shuffle")

import portable as PT

sd = PT.selection_seed("ab" * 32, "cd" * 16)
check("selection seed is 32 bytes", len(sd) == 32)
check("seed deterministic", sd == PT.selection_seed("ab" * 32, "cd" * 16))
check("seed changes with commitment", sd != PT.selection_seed("ff" * 32, "cd" * 16))
check("seed changes with beacon", sd != PT.selection_seed("ab" * 32, "ee" * 16))

o = PT.shuffle_indices(sd, 64)
check("shuffle is a permutation", sorted(o) == list(range(64)))
check("shuffle deterministic", o == PT.shuffle_indices(sd, 64))
check("shuffle differs for a different seed",
      o != PT.shuffle_indices(PT.selection_seed("ff" * 32, "cd" * 16), 64))
check("shuffle handles n=1", PT.shuffle_indices(sd, 1) == [0])
check("shuffle handles n=0", PT.shuffle_indices(sd, 0) == [])

# Rejection sampling must be unbiased: every permutation of n=4 should appear
# with roughly equal frequency. A plain-modulo implementation fails this.
cnt = collections_Counter = {}
for k in range(24000):
    p = tuple(PT.shuffle_indices(PT.selection_seed("11" * 32, str(k)), 4))
    cnt[p] = cnt.get(p, 0) + 1
vals = sorted(cnt.values())
expected = 24000 / 24
check("all 24 permutations of n=4 appear", len(cnt) == 24, f"got {len(cnt)}")
check("permutation frequencies within 4 sigma of uniform",
      abs(vals[0] - expected) < 4 * (expected ** 0.5)
      and abs(vals[-1] - expected) < 4 * (expected ** 0.5),
      f"min={vals[0]} max={vals[-1]} expected~{expected:.0f}")

# uniform_below must never return >= m and must terminate
strm = PT.drbg_stream(sd)
check("uniform_below in range", all(0 <= PT.uniform_below(strm, m) < m
                                    for m in (1, 2, 3, 7, 100, 65535)))

# published cross-language test vectors must be stable
tv = PT.test_vectors()
check("selection vectors present", len(tv["selection"]) == 3)
check("item-stream vectors present", len(tv["item_stream"]) == 3)
check("test vectors stable", tv == PT.test_vectors())
check("test vector orders are permutations",
      all(sorted(t["order"]) == list(range(t["n"])) for t in tv["selection"]))

section("portable POOL generation (v0.3): the other half of portability")

# v0.2 made the shuffle portable but left pool generation on CPython's
# Mersenne Twister -- so a verifier could not regenerate the pool, and
# receipts were still Python-only. These lock that closed.
pr = PT.PortableRandom(PT.item_seed(1, 0, 0))
check("randint respects inclusive bounds",
      all(3 <= pr.randint(3, 9) <= 9 for _ in range(500)))
check("randint(a,a) is a", PT.PortableRandom(PT.item_seed(1, 0, 1)).randint(5, 5) == 5)
check("randrange in [0,n)",
      all(0 <= pr.randrange(7) < 7 for _ in range(500)))
check("choice returns a member",
      all(pr.choice(["x", "y", "z"]) in ("x", "y", "z") for _ in range(300)))
s4 = PT.PortableRandom(PT.item_seed(2, 0, 0)).sample(list(range(10)), 4)
check("sample returns k distinct in-range items",
      len(s4) == 4 and len(set(s4)) == 4 and all(0 <= v < 10 for v in s4), str(s4))
check("sample k=0 is empty", PT.PortableRandom(PT.item_seed(2, 0, 1)).sample([1, 2], 0) == [])
try:
    PT.PortableRandom(PT.item_seed(2, 0, 2)).sample([1, 2], 5)
    check("sample rejects k > len", False, "no exception")
except ValueError:
    check("sample rejects k > len", True)

check("item_seed is 32 bytes", len(PT.item_seed(1, 2, 3)) == 32)
check("item_seed varies with every component",
      len({PT.item_seed(1, 2, 3), PT.item_seed(2, 2, 3),
           PT.item_seed(1, 9, 3), PT.item_seed(1, 2, 9)}) == 4)

# pools must be deterministic, portable-by-default, and distinct from legacy
pa = C.make_pool(20260808, 25, 0, ["state_track"])
check("portable pool deterministic",
      C.pool_commitment(pa) == C.pool_commitment(
          C.make_pool(20260808, 25, 0, ["state_track"])))
check("portable is the default",
      C.pool_commitment(pa) == C.pool_commitment(
          C.make_pool(20260808, 25, 0, ["state_track"], portable_mode=True)))
check("portable pool differs from legacy pool",
      C.pool_commitment(pa) != C.pool_commitment(
          C.make_pool(20260808, 25, 0, ["state_track"], portable_mode=False)))

# every family must generate on every tier under the portable RNG
gen_ok = True
for fam in ("state_track", "word_index", "money_chain", "date_offset", "set_logic"):
    for dd in range(6):
        try:
            if len(C.make_pool(4242, 12, dd, [fam])) != 12:
                gen_ok = False
        except Exception:
            gen_ok = False
check("all 5 families generate on all 6 tiers (portable)", gen_ok)

# ground truth must remain exact under the portable RNG
bad = n = 0
for dd in range(6):
    for it in C.make_pool(31337, 120, dd, ["state_track"]):
        m = re.match(r"Start with the number (\d+), then (.+)\. What", it["q"])
        cur = int(m.group(1))
        for op in m.group(2).split(", then "):
            if op.startswith("add"):
                cur += int(op.split()[1])
            elif op.startswith("subtract"):
                cur -= int(op.split()[1])
            else:
                cur *= int(op.split()[-1])
        n += 1
        bad += str(cur) != it["a"]
check("portable pools carry exact ground truth", bad == 0, f"{bad}/{n} wrong")

section("version-scoped verification: v0.1 receipts stay verifiable")

# A genuine v0.1 receipt used BOTH legacy derivations -- the CPython pool
# generator AND the CPython shuffle. Build the fixture that way, or it is not
# actually a v0.1 receipt and the test proves nothing. (An earlier version of
# this test built a portable pool and merely relabelled it v0.1; it failed,
# correctly, once pool generation became version-scoped.)
legacy_pool = C.make_pool(20260808, 120, 0, ["state_track", "money_chain"],
                          portable_mode=False)
legacy_c = C.pool_commitment(legacy_pool)
check("legacy pool differs from portable pool", legacy_c != c1)

legacy_order = H.selection_order(legacy_c, beacon, len(legacy_pool),
                                 "heartwood/0.1")
check("v0.1 shuffle differs from v0.3 shuffle",
      legacy_order != H.selection_order(legacy_c, beacon, len(legacy_pool),
                                        "heartwood/0.3"))

legacy_t = []
for item_id in legacy_order[:30]:
    it = legacy_pool[item_id]
    resp = f"ANSWER: {it['a']}" if rng.random() < 0.10 else "ANSWER: 0"
    legacy_t.append({
        "item_id": item_id, "served_mode": "hollow",
        "question_sha256": H.sha(it["q"]), "response": resp,
        "response_sha256": H.sha(resp),
        "graded": E.grade(E.extract(resp), it["a"], resp)})

legacy_plan = dict(plan)
legacy_plan["pool_size"] = 120
v01 = H.build_receipt(20260808, 0, legacy_c, beacon, legacy_plan, {"n": 36},
                      legacy_t, "testhash")
v01["version"] = "heartwood/0.1"
vv = H.verify_receipt(v01)
check("v0.1 receipt verifies under v0.3 code", vv["valid"], str(vv["checks"]))

# and a v0.1 receipt must NOT verify if relabelled as a later version
for relabel in ("heartwood/0.2", "heartwood/0.3"):
    m = copy.deepcopy(v01)
    m["version"] = relabel
    check(f"relabelling v0.1 as {relabel} is caught",
          not H.verify_receipt(m)["valid"])


# ----------------------------------------------------------------- done ----
print()
if FAILS:
    print(f"FAILED {len(FAILS)}/{COUNT[0]}")
    for f in FAILS:
        print("   -", f)
    sys.exit(1)
print(f"PASSED {COUNT[0]}/{COUNT[0]}")
