r"""Stage 3b -- chaos: boundary inputs by mutating a generated matching string.

Why this exists: Stage 2 builds a grammar OF
THE REGEX'S LANGUAGE and Stage 3 samples it, so every generated string is a
positive example by construction -- measured at 98.5% over the 6000-9999 window.
Both bugs found so far live just OUTSIDE that language: ``regex_5354`` (bun anchor)
needs a leading pad the regex does not match, and ``/\p{Lu}/iu`` (bun property-escape
folding) needs a lowercase letter, which ``\p{Uppercase_Letter}`` by construction
never generates. The negative half of every API's behaviour (``test`` -> false,
``exec`` -> null, ``split`` -> [whole string]) is starved for the same reason.

So: take a string the grammar produced and perturb it slightly.

**A mutant is NOT required to leave the language, and often will not** -- deleting
one ``a`` from ``aaa`` still matches ``a+``. That is fine and is the point. The
mutation lands NEAR the boundary, which is where anchor and backtracking bugs live,
and an in-language mutant is still a string the grammar may never have sampled.
Which side of the boundary each mutant landed on is *measured*, not assumed:
Stage 3 records ``py_re_matches`` per string exactly as it does for fuzz strings,
and every record carries ``origin`` so the two populations are never conflated.

Uniform: the same op set and selection rule apply to
every regex and every API. Nothing here branches on a regex id or an api name.

Determinism and provenance: mutants are drawn from a caller-supplied
:class:`random.Random` seeded via :func:`rng_for` from
``(config.seed, regex_id, api, seed index)``. This is a LOCAL rng -- the global
``random`` module is never touched -- so a mutant depends only on its seed string
and the provenance quadruple, never on how many rows preceded it in the process.
That last property is deliberate: G6 (open) suspects exactly such a positional
dependency, via an unseeded probe on a shared object, of making artifacts
irreproducible from recorded provenance. A mutant is fully reconstructible from
its record: seed string at ``seed_n``, plus ``mutation``.
"""

from __future__ import annotations

import hashlib
import random
from typing import Callable

# An op takes (string, rng, alphabet) and returns (mutant, label), or None when it
# does not apply to this string (transpose needs >=2 chars, case_flip needs a
# cased char). Returning None rather than raising lets the caller just try another
# op -- an inapplicable op is normal, not an error.
Op = Callable[[str, random.Random, tuple[str, ...]], "tuple[str, str] | None"]

# How many draws before we give up producing a distinct mutant for one slot. A
# short string has few distinct mutants (`"a"` has exactly one under `delete`), so
# collisions with already-seen strings are expected; this bounds the retry rather
# than looping forever. Not a tuned experiment parameter -- a loop bound.
_MAX_DRAWS = 12


def _op_delete(s: str, rng: random.Random, alphabet: tuple[str, ...]):
    """Drop one character. On a 1-char string this yields ``""`` -- a real negative."""
    if not s:
        return None
    i = rng.randrange(len(s))
    return s[:i] + s[i + 1:], f"delete@{i}"


def _op_insert(s: str, rng: random.Random, alphabet: tuple[str, ...]):
    """Insert one alphabet character at any position, including the ends. A
    leading insert is the cheap general form of the ``<pad>`` that ``matchAll``
    already gets and the other four APIs never do (G3a) -- what ``regex_5354``
    needed."""
    i = rng.randrange(len(s) + 1)
    c = rng.choice(alphabet)
    return s[:i] + c + s[i:], f"insert@{i}"


def _op_substitute(s: str, rng: random.Random, alphabet: tuple[str, ...]):
    if not s:
        return None
    i = rng.randrange(len(s))
    c = rng.choice(alphabet)
    return s[:i] + c + s[i + 1:], f"substitute@{i}"


def _op_duplicate(s: str, rng: random.Random, alphabet: tuple[str, ...]):
    if not s:
        return None
    i = rng.randrange(len(s))
    return s[:i] + s[i] + s[i:], f"duplicate@{i}"


def _op_transpose(s: str, rng: random.Random, alphabet: tuple[str, ...]):
    """Swap two adjacent characters.

    Only positions where the two characters DIFFER are candidates: swapping the
    ``ll`` in ``"Hello"`` returns the input unchanged, which is a wasted mutant
    slot, not a mutation. A string of one repeated character (``"aaa"``) has no
    such position and declines.
    """
    swappable = [i for i in range(len(s) - 1) if s[i] != s[i + 1]]
    if not swappable:
        return None
    i = rng.choice(swappable)
    return s[:i] + s[i + 1] + s[i] + s[i + 2:], f"transpose@{i}"


def _op_case_flip(s: str, rng: random.Random, alphabet: tuple[str, ...]):
    """Flip the case of one cased character.

    This is the op that reaches G3b. Flag variants already run every string under
    ``i``, but the inputs were never case-varied, so ``regex_9921``
    (``\\p{Uppercase_Letter}``) was tested under ``giu`` against 20 strings of which
    0 contained a lowercase letter, and the bun folding bug went unseen. A
    case-flipped mutant is run under the same existing ``i`` variants.
    """
    cased = [i for i, c in enumerate(s) if c.swapcase() != c]
    if not cased:
        return None
    i = rng.choice(cased)
    return s[:i] + s[i].swapcase() + s[i + 1:], f"case_flip@{i}"


def _op_truncate(s: str, rng: random.Random, alphabet: tuple[str, ...]):
    """Cut the string at a point, keeping either the head or the tail. Unlike
    ``delete`` this removes a whole run, which is what breaks a multi-part match."""
    if len(s) < 2:
        return None
    i = rng.randrange(1, len(s))
    if rng.random() < 0.5:
        return s[i:], f"truncate_head@{i}"
    return s[:i], f"truncate_tail@{i}"


# The registry is the single source of valid op names; config validates against it,
# so an unknown op in YAML fails loud at load rather than silently doing nothing.
OPS: dict[str, Op] = {
    "delete": _op_delete,
    "insert": _op_insert,
    "substitute": _op_substitute,
    "duplicate": _op_duplicate,
    "transpose": _op_transpose,
    "case_flip": _op_case_flip,
    "truncate": _op_truncate,
}


def rng_for(seed: int, rid: str, api: str, seed_n: int) -> random.Random:
    """A local rng for the mutants of one (regex, api, seed string).

    Derived by sha256 rather than :func:`hash` so it is stable across processes
    (``hash`` on ``str`` is salted per interpreter by PYTHONHASHSEED -- it would
    make mutants unreproducible across runs, which is the whole point of seeding).
    """
    h = hashlib.sha256(f"{seed}|{rid}|{api}|{seed_n}".encode("utf-8")).hexdigest()
    return random.Random(int(h[:16], 16))


def mutate(s: str, rng: random.Random, ops: tuple[str, ...],
           alphabet: tuple[str, ...]) -> "tuple[str, str] | None":
    """One mutant of `s` as ``(mutant, label)``, or None if no enabled op applied.

    Picks ONE op per mutant -- not a stack of them. A single perturbation keeps the
    mutant on the boundary (the interesting place) and keeps ``mutation`` legible
    enough that a reader can reconstruct the mutant from the seed string by hand.
    An op that does not apply to this string is re-drawn.
    """
    pool = list(ops)
    rng.shuffle(pool)
    for name in pool:
        out = OPS[name](s, rng, alphabet)
        if out is not None and out[0] != s:
            return out
    return None


def mutants(s: str, count: int, rng: random.Random, ops: tuple[str, ...],
            alphabet: tuple[str, ...], seen: set[str]) -> list[tuple[str, str]]:
    """Up to `count` distinct mutants of `s`, as ``(mutant, label)`` pairs.

    `seen` is every string already accepted for this (regex, api) -- the fuzz
    strings plus earlier mutants. A mutant colliding with one of them is dropped
    rather than emitted: it would produce a byte-identical duplicate harness set
    and inflate the case count without testing anything new. `seen` is NOT mutated
    here; the caller owns it.

    Fewer than `count` (or zero) is a normal outcome for a short or uncased string,
    not an error -- ``"a"`` admits few distinct single-op mutants.
    """
    out: list[tuple[str, str]] = []
    local = set(seen)
    for _ in range(count):
        for _ in range(_MAX_DRAWS):
            m = mutate(s, rng, ops, alphabet)
            if m is None:
                return out  # no enabled op applies to this string at all
            if m[0] not in local:
                local.add(m[0])
                out.append(m)
                break
    return out
