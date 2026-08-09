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


def test_vectors():
    """Cross-language test vectors. An independent implementation that
    reproduces these is interoperable with this one."""
    out = []
    for commitment, randomness, n in (
        ("00" * 32, "aa" * 16, 8),
        ("11" * 32, "bb" * 16, 16),
        ("deadbeef" * 8, None, 32),
    ):
        seed = selection_seed(commitment, randomness)
        out.append({
            "pool_commitment": commitment,
            "beacon_randomness": randomness,
            "n": n,
            "seed_sha256": seed.hex(),
            "order": shuffle_indices(seed, n),
        })
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(test_vectors(), indent=1))
