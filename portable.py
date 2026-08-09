"""Portable, language-independent primitives for Heartwood v0.2.

WHY THIS EXISTS
    v0.1 derived the challenge order with Python's `random.Random.shuffle`.
    That reproduces only under CPython, so a Rust or Go verifier could not
    recompute the beacon-derived order and the receipt was not actually
    portable -- a real interop bug in a protocol whose entire value is that
    anyone can recheck it.

    v0.2 specifies the shuffle exactly, in terms every language already has:
    HMAC-SHA256 in counter mode as the random source, and Fisher-Yates with
    rejection sampling for unbiased index selection. No ChaCha20, no crypto
    dependency -- HMAC-SHA256 is in every standard library, which is the
    property that matters for an independently implementable spec.
"""
import hashlib
import hmac

WORD = 8            # bytes per drawn integer
BITS = WORD * 8
LIMIT = 1 << BITS


def drbg_stream(seed: bytes):
    """Deterministic byte source: HMAC-SHA256(seed, counter) blocks, counter
    starting at 0, big-endian 8-byte counter. Yields 8-byte words."""
    counter = 0
    while True:
        block = hmac.new(seed, counter.to_bytes(8, "big"), hashlib.sha256).digest()
        for off in range(0, len(block), WORD):
            yield block[off:off + WORD]
        counter += 1


def uniform_below(stream, m: int) -> int:
    """Unbiased integer in [0, m) via rejection sampling.

    Plain modulo would bias low indices; rejection keeps the permutation
    uniform and is trivially reimplementable in any language.
    """
    if m <= 0:
        raise ValueError("m must be positive")
    bound = LIMIT - (LIMIT % m)          # largest multiple of m below 2^64
    while True:
        v = int.from_bytes(next(stream), "big")
        if v < bound:
            return v % m


def shuffle_indices(seed: bytes, n: int):
    """Fisher-Yates over range(n), driven by the DRBG.

    Iterates i from n-1 down to 1, drawing j uniformly in [0, i] and swapping.
    Specified precisely so an independent implementation matches byte for byte.
    """
    idx = list(range(n))
    stream = drbg_stream(seed)
    for i in range(n - 1, 0, -1):
        j = uniform_below(stream, i + 1)
        idx[i], idx[j] = idx[j], idx[i]
    return idx


def selection_seed(pool_commitment: str, beacon_randomness) -> bytes:
    """Bind the ordering to the committed pool AND the public beacon."""
    material = f"{pool_commitment}|{beacon_randomness}".encode("utf-8")
    return hashlib.sha256(material).digest()


class PortableRandom:
    """A specified, language-independent stand-in for `random.Random`.

    v0.2 made the SHUFFLE portable but left POOL GENERATION on CPython's
    Mersenne Twister -- and a verifier must regenerate the pool to check the
    commitment and to re-grade. So receipts were still Python-only: one of the
    two derivations was fixed and both were claimed. This closes the other.

    Exposes only the surface the generators use (randint / choice / sample),
    each defined in terms of the HMAC-SHA256 DRBG above so any language can
    reproduce it.
    """

    def __init__(self, seed: bytes):
        self._stream = drbg_stream(seed)

    def randint(self, a: int, b: int) -> int:
        """Inclusive on both ends, matching random.randint's contract."""
        if b < a:
            raise ValueError(f"empty range [{a}, {b}]")
        return a + uniform_below(self._stream, b - a + 1)

    def randrange(self, n: int) -> int:
        """Half-open [0, n), matching random.randrange(n)."""
        return uniform_below(self._stream, n)

    def choice(self, seq):
        if not seq:
            raise IndexError("choice from empty sequence")
        return seq[uniform_below(self._stream, len(seq))]

    def sample(self, seq, k: int):
        """k distinct items, in draw order.

        Partial Fisher-Yates over a copy: swap each of the first k slots with
        a uniformly chosen slot at or after it, then take the prefix. Simple
        enough to restate in one sentence in the spec.
        """
        pool = list(seq)
        if not 0 <= k <= len(pool):
            raise ValueError(f"sample size {k} out of range for {len(pool)}")
        for i in range(k):
            j = i + uniform_below(self._stream, len(pool) - i)
            pool[i], pool[j] = pool[j], pool[i]
        return pool[:k]


def item_seed(pool_seed: int, difficulty: int, idx: int) -> bytes:
    """Per-item DRBG seed. Independent across items and reproducible."""
    return hashlib.sha256(
        f"heartwood-item|{pool_seed}|{difficulty}|{idx}".encode("utf-8")
    ).digest()


def test_vectors():
    """Cross-language test vectors. An independent implementation that
    reproduces these is interoperable with this one.

    Covers BOTH derivations a verifier needs: the beacon-bound selection order,
    and the per-item random stream that regenerates the challenge pool. v0.2
    published only the first, which is why v0.2 receipts were still
    Python-only in practice.
    """
    out = {"selection": [], "item_stream": []}
    for commitment, randomness, n in (
        ("00" * 32, "aa" * 16, 8),
        ("11" * 32, "bb" * 16, 16),
        ("deadbeef" * 8, None, 32),
    ):
        seed = selection_seed(commitment, randomness)
        out["selection"].append({
            "pool_commitment": commitment,
            "beacon_randomness": randomness,
            "n": n,
            "seed_sha256": seed.hex(),
            "order": shuffle_indices(seed, n),
        })
    for pool_seed, difficulty, idx in ((20260808, 0, 0), (20260808, 3, 7),
                                       (1, 5, 42)):
        sd = item_seed(pool_seed, difficulty, idx)
        r = PortableRandom(sd)
        out["item_stream"].append({
            "pool_seed": pool_seed, "difficulty": difficulty, "idx": idx,
            "item_seed_sha256": sd.hex(),
            "randint_1_100": [r.randint(1, 100) for _ in range(5)],
            "randrange_7": [r.randrange(7) for _ in range(5)],
            "choice_abcde": [r.choice(list("abcde")) for _ in range(5)],
            "sample_0to9_k4": r.sample(list(range(10)), 4),
        })
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(test_vectors(), indent=1))
