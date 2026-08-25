"""Unit tests for pipeline.chaos -- boundary inputs from mutated strings.

conftest.py puts ``src`` on the path. These are pure (no Fandango, no engines).

The properties that matter here are determinism and honest provenance: a mutant
must be reproducible from (seed, rid, api, seed_n) alone, and its ``mutation``
label must actually describe what happened to it.
"""

import random

import pytest

from pipeline.chaos import OPS, mutate, mutants, rng_for

ALPHA = ("a", "Z", "0", " ", "\n", "é", "𐐷")
ALL_OPS = tuple(OPS)


def _rng():
    return random.Random(1234)


# --- individual ops: each must change the string, or decline ------------------

class TestOps:
    @pytest.mark.parametrize("op", ALL_OPS)
    def test_changes_or_declines(self, op):
        """An op either returns a genuinely different string or None. Returning the
        input unchanged would burn a mutant slot on a duplicate harness."""
        rng = random.Random(7)
        for _ in range(50):
            out = OPS[op]("Hello World 42", rng, ALPHA)
            assert out is not None, f"{op} should apply to a rich string"
            mutant, label = out
            assert mutant != "Hello World 42"
            assert label.startswith(op.split("_")[0]) or op in label

    @pytest.mark.parametrize("op", ALL_OPS)
    def test_empty_string_never_crashes(self, op):
        """An empty seed is reachable: `delete` on a 1-char string yields "". Ops
        must decline, not raise."""
        out = OPS[op]("", _rng(), ALPHA)
        assert out is None or isinstance(out[0], str)

    def test_transpose_needs_two_chars(self):
        assert OPS["transpose"]("a", _rng(), ALPHA) is None

    def test_transpose_declines_rather_than_no_op(self):
        """Swapping two identical adjacent chars returns the input unchanged, which
        is a wasted mutant slot. Only differing pairs are candidates."""
        assert OPS["transpose"]("aaaa", _rng(), ALPHA) is None
        rng = random.Random(3)
        for _ in range(30):
            # every swappable position in "Hello" is around the `ll`
            mutant, _ = OPS["transpose"]("Hello", rng, ALPHA)
            assert mutant != "Hello"

    def test_case_flip_needs_a_cased_char(self):
        assert OPS["case_flip"]("123 !?", _rng(), ALPHA) is None
        out = OPS["case_flip"]("abc", _rng(), ALPHA)
        assert out is not None and out[0] in ("Abc", "aBc", "abC")

    def test_delete_of_single_char_gives_empty(self):
        assert OPS["delete"]("x", _rng(), ALPHA) == ("", "delete@0")

    def test_truncate_keeps_a_contiguous_run(self):
        mutant, label = OPS["truncate"]("abcdef", _rng(), ALPHA)
        assert mutant and ("abcdef".startswith(mutant) or "abcdef".endswith(mutant))
        assert mutant != "abcdef"

    def test_insert_can_prepend(self):
        """A leading insert is the general form of matchAll's <pad> -- the shape
        regex_5354 needed (G3a). It must be reachable, i.e. position 0 included."""
        rng = random.Random(0)
        seen_prefix = any(
            OPS["insert"]("abc", rng, ALPHA)[1] == "insert@0" for _ in range(100)
        )
        assert seen_prefix

    def test_astral_char_is_one_unit(self):
        """Python indexes by code point, so an astral char is atomic and `delete`
        cannot leave a lone surrogate. F001's witnesses are astral; splitting one
        would silently change what the mutant tests."""
        assert OPS["delete"]("𐐷", _rng(), ALPHA) == ("", "delete@0")


# --- determinism: the G6-shaped property -------------------------------------

class TestDeterminism:
    def test_rng_is_stable_across_calls(self):
        a = [rng_for(0, "regex_1", "exec", 3).random() for _ in range(3)]
        assert len(set(a)) == 1, "rng_for must be a pure function of its inputs"

    @pytest.mark.parametrize("differing", [
        {"seed": 1}, {"rid": "regex_2"}, {"api": "test"}, {"seed_n": 4},
    ])
    def test_rng_varies_with_every_input(self, differing):
        base = {"seed": 0, "rid": "regex_1", "api": "exec", "seed_n": 3}
        other = {**base, **differing}
        assert rng_for(**base).random() != rng_for(**other).random()

    def test_mutants_reproduce_from_provenance_alone(self):
        """The whole point: same (seed, rid, api, seed_n) -> byte-identical mutants,
        with no dependence on how many strings were mutated before this one."""
        first = mutants("Hello World", 2, rng_for(0, "regex_1", "exec", 0),
                        ALL_OPS, ALPHA, set())
        # A different call site, with unrelated global rng churn in between.
        random.seed(99)
        [random.random() for _ in range(1000)]
        second = mutants("Hello World", 2, rng_for(0, "regex_1", "exec", 0),
                         ALL_OPS, ALPHA, set())
        assert first == second

    def test_does_not_touch_global_random(self):
        """chaos must never consume the global rng: doing so would make every
        LATER consumer depend on how many rows preceded it -- the positional
        dependency G6 suspects of breaking artifact reproducibility."""
        random.seed(42)
        expected = [random.random() for _ in range(5)]
        random.seed(42)
        mutants("Hello World", 5, rng_for(0, "regex_1", "exec", 0),
                ALL_OPS, ALPHA, set())
        assert [random.random() for _ in range(5)] == expected


# --- mutants(): count, distinctness, exclusion -------------------------------

class TestMutants:
    def test_returns_requested_count_for_a_rich_string(self):
        out = mutants("Hello World 42", 2, _rng(), ALL_OPS, ALPHA, set())
        assert len(out) == 2

    def test_mutants_are_distinct_from_each_other(self):
        out = mutants("Hello World 42", 5, _rng(), ALL_OPS, ALPHA, set())
        assert len({m for m, _ in out}) == len(out)

    def test_respects_seen_and_does_not_mutate_it(self):
        """A mutant colliding with an existing string is dropped -- it would emit a
        byte-identical harness set and inflate the case count for nothing."""
        seen = {"ab", "b", "a", "aab", "abb", "ba"}
        snapshot = set(seen)
        out = mutants("ab", 3, _rng(), ("delete", "duplicate", "transpose"),
                      ALPHA, seen)
        assert all(m not in snapshot for m, _ in out)
        assert seen == snapshot, "mutants() must not mutate the caller's set"

    def test_fewer_than_requested_is_normal(self):
        """"a" under delete-only admits exactly one distinct mutant ("")."""
        out = mutants("a", 4, _rng(), ("delete",), ALPHA, set())
        assert len(out) == 1

    def test_no_applicable_op_returns_empty(self):
        out = mutants("1", 2, _rng(), ("case_flip", "transpose"), ALPHA, set())
        assert out == []

    def test_label_reconstructs_the_mutant(self):
        """`mutation` is provenance, so it must be true. Replay each label against
        its seed string and check it lands on the recorded mutant."""
        seed = "Hello World 42"
        for mutant, label in mutants(seed, 8, _rng(), ALL_OPS, ALPHA, set()):
            op, _, pos = label.partition("@")
            i = int(pos)
            if op == "delete":
                assert mutant == seed[:i] + seed[i + 1:]
            elif op == "duplicate":
                assert mutant == seed[:i] + seed[i] + seed[i:]
            elif op == "transpose":
                assert mutant == seed[:i] + seed[i + 1] + seed[i] + seed[i + 2:]
            elif op == "case_flip":
                assert mutant == seed[:i] + seed[i].swapcase() + seed[i + 1:]
            elif op == "truncate_head":
                assert mutant == seed[i:]
            elif op == "truncate_tail":
                assert mutant == seed[:i]
            elif op == "insert":
                assert mutant[:i] == seed[:i] and mutant[i + 1:] == seed[i:]
                assert mutant[i] in ALPHA
            elif op == "substitute":
                assert mutant[:i] == seed[:i] and mutant[i + 1:] == seed[i + 1:]
                assert mutant[i] in ALPHA
            else:
                pytest.fail(f"unhandled op label {label!r}")


# --- mutate(): op selection ---------------------------------------------------

class TestMutate:
    def test_only_enabled_ops_are_used(self):
        for _ in range(30):
            out = mutate("Hello World", _rng(), ("delete",), ALPHA)
            assert out is not None and out[1].startswith("delete@")

    def test_declines_when_nothing_applies(self):
        assert mutate("", _rng(), ("transpose", "case_flip"), ALPHA) is None
