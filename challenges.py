"""Heartwood capability-cliff challenge generator.

Design requirements:
  1. Ground truth computable in Python (no LLM judge).
  2. Sharp capability threshold -- requires genuine sequential work, cannot be
     guessed from surface features.
  3. Surface form indistinguishable from ordinary user traffic.
  4. Deterministic given a seed, so the whole pool is reproducible from a
     committed seed (needed for the transparency commitment).

Difficulty is a tunable knob. Per-query information is maximised at the
CLIFF EDGE -- where the claimed model still succeeds but a low-effort
substitute does not. Items that are too hard (both fail) or too easy (both
pass) carry no evidence, so difficulty must be calibrated to the claimed
model, not chosen for absolute hardness.
"""
import hashlib
import random

import portable

DIFF = {
    0: {"ops": (2, 2), "mulmax": 2, "start": (5, 15), "addmax": 6,
        "words": (3, 4), "qty": (2, 3), "price": (2, 5), "off": (2, 6),
        "grp": (8, 14)},
    1: {"ops": (2, 3), "mulmax": 2, "start": (5, 20), "addmax": 9,
        "words": (4, 5), "qty": (2, 4), "price": (2, 6), "off": (2, 9),
        "grp": (12, 20)},
    2: {"ops": (3, 4), "mulmax": 3, "start": (10, 40), "addmax": 12,
        "words": (5, 7), "qty": (3, 6), "price": (3, 9), "off": (8, 20),
        "grp": (20, 35)},
    3: {"ops": (4, 6), "mulmax": 4, "start": (10, 99), "addmax": 19,
        "words": (7, 9), "qty": (4, 9), "price": (3, 12), "off": (9, 40),
        "grp": (30, 60)},
    # Tiers 4-5 exist for FRONTIER models. A capability cliff is relative to
    # the claimed model: tiers 0-3 are calibrated to a 2B local model and a
    # frontier model solves them without spending any real compute, so they
    # carry no evidence there. Longer dependency chains restore the cliff --
    # each step depends on the last, so the work cannot be skipped.
    4: {"ops": (7, 9), "mulmax": 3, "start": (10, 99), "addmax": 25,
        "words": (9, 12), "qty": (4, 9), "price": (3, 12), "off": (20, 60),
        "grp": (40, 90)},
    5: {"ops": (11, 14), "mulmax": 3, "start": (10, 99), "addmax": 40,
        "words": (11, 14), "qty": (5, 12), "price": (4, 18), "off": (30, 120),
        "grp": (60, 140)},
}

WORDS = ["river", "candle", "orbit", "meadow", "anchor", "puzzle", "lantern",
         "harvest", "marble", "thunder", "willow", "compass", "ember", "gravel"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday", "Sunday"]


def _rng(seed: int, idx: int, difficulty: int = 0, portable_mode: bool = True):
    """Per-item random source.

    portable_mode=True  -> HMAC-SHA256 DRBG (see portable.py). Any language can
                           regenerate the identical pool, which is what makes a
                           receipt verifiable off-Python.
    portable_mode=False -> CPython's Mersenne Twister, retained ONLY so that
                           receipts issued under heartwood/0.1 and /0.2 remain
                           verifiable. Do not use it for new pools.
    """
    if portable_mode:
        return portable.PortableRandom(portable.item_seed(seed, difficulty, idx))
    h = hashlib.sha256(f"{seed}:{idx}".encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


def state_track(r, d):
    n = r.randint(*d["start"])
    ops, cur = [], n
    for _ in range(r.randint(*d["ops"])):
        k = r.choice(["add", "mul", "sub"])
        if k == "add":
            v = r.randint(2, d["addmax"]); cur += v; ops.append(f"add {v}")
        elif k == "sub":
            v = r.randint(2, min(d["addmax"], max(2, cur - 1)))
            cur -= v; ops.append(f"subtract {v}")
        else:
            v = r.randint(2, d["mulmax"]); cur *= v
            ops.append(f"multiply by {v}")
    q = (f"Start with the number {n}, then {', then '.join(ops)}. "
         f"What number do you end up with?")
    return q, str(cur)


def word_index(r, d):
    words = r.sample(WORDS, r.randint(*d["words"]))
    i = r.randint(2, len(words) - 1)
    q = (f"Consider this list: {', '.join(words)}. "
         f"Counting from the left starting at 1, what is word number {i}?")
    return q, words[i - 1]


def money_chain(r, d):
    """Order total with a percentage discount.

    The discount MUST divide the order total exactly. Without this constraint
    integer division silently produces a wrong ground truth -- e.g. $4 x 3 with
    10% off scored the true answer $10.80 as 11, marking a CORRECT model wrong.
    """
    for _ in range(200):
        price = r.randint(*d["price"])
        qty = r.randint(*d["qty"])
        disc = r.choice([10, 50] if d["qty"][1] <= 4 else [5, 10, 20, 25])
        total = price * qty
        if (total * disc) % 100 == 0:
            break
    else:  # guaranteed-exact fallback
        price, qty, disc = 10, r.randint(*d["qty"]), 50
        total = price * qty
    final = total - total * disc // 100
    q = (f"An item costs ${price} and I buy {qty} of them. "
         f"A {disc}% discount applies to the whole order. "
         f"What is the final total in dollars?")
    return q, str(final)


def date_offset(r, d):
    start = r.randrange(7)
    off = r.randint(*d["off"])
    q = (f"If today is {DAYS[start]}, what day of the week "
         f"is it {off} days from now?")
    return q, DAYS[(start + off) % 7]


def set_logic(r, d):
    total = r.randint(*d["grp"])
    a = r.randint(max(3, total // 4), max(4, total // 2))
    b = r.randint(max(3, total // 4), max(4, total // 2))
    both = r.randint(1, max(1, min(a, b) - 1))
    neither = total - (a + b - both)
    if neither < 0:
        total = a + b - both + r.randint(1, 5)
        neither = total - (a + b - both)
    q = (f"In a group of {total} people, {a} like tea and {b} like coffee, "
         f"and {both} like both. How many like neither?")
    return q, str(neither)


GENERATORS = [state_track, word_index, money_chain, date_offset, set_logic]


def make_pool(seed: int, n: int, difficulty: int = 2, families=None,
              portable_mode: bool = True):
    """Deterministic pool of (id, question, answer, family).

    `families` restricts the pool to the CAPABILITY BAND of the claimed model.
    This matters more than it looks: an item the claimed model cannot solve
    carries no evidence, because it reads as a failure whether the endpoint is
    honest or hollowed. Per-query information is maximised only where the
    claimed model reliably succeeds and a low-effort substitute does not.
    The band is chosen during calibration on a DISJOINT pool and then frozen
    into the commitment, so this is not post-hoc selection on audit data.
    """
    d = DIFF[difficulty]
    gens = [g for g in GENERATORS
            if families is None or g.__name__ in families]
    if not gens:
        raise ValueError(f"no generators match families={families}")
    pool = []
    for i in range(n):
        r = _rng(seed * 10 + difficulty, i, difficulty, portable_mode)
        g = gens[i % len(gens)]
        q, a = g(r, d)
        pool.append({"id": i, "q": q, "a": a,
                     "family": g.__name__, "difficulty": difficulty})
    return pool


def pool_commitment(pool):
    """Binding commitment over the full pool (questions AND answers)."""
    h = hashlib.sha256()
    for it in pool:
        h.update(f"{it['id']}\x1f{it['q']}\x1f{it['a']}\x1e".encode())
    return h.hexdigest()


if __name__ == "__main__":
    for lvl in (1, 2, 3):
        p = make_pool(20260808, 5, lvl)
        print(f"--- difficulty {lvl} ---")
        for it in p:
            print(f"  {it['q'][:88]}  -> {it['a']}")
