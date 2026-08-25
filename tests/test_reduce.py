"""Unit tests for analysis/eval_help_scripts/reduce.py -- the differential reducer.

conftest.py puts ``src`` on the path; the reducer lives outside it, so this module adds
``analysis/eval_help_scripts`` too. Everything tested here is PURE -- no engines, no
subprocesses -- which is the point: the parts most likely to regress (ddmin, the
tokenizers, the key derivations) are exactly the parts that need no engine to exercise.

Two of these are REGRESSION tests for bugs that shipped and were caught by reading batch
output rather than by any check:

  * ``ddmin`` exited its loop at ``len(seq) < 2`` and so never tested removing the last
    element -- the empty set was unreachable. Cost: one bug reported as five separate
    mechanism clusters (flags "", d, g, i, m), because ``""`` witnessed it but a 1-char
    flag string could never reduce to ``""``.
  * ``repro_js`` emitted a bare ``re.exec(s)`` for a ``g``/``y`` regex. The harness runs a
    lastIndex PRESET BATTERY, so a divergence living at ``preset_1`` does not reproduce
    from lastIndex 0 -- the tool was emitting confidently wrong reproducers.
"""

import os
import sys

import pytest

_HELP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "analysis", "eval_help_scripts")
if _HELP not in sys.path:
    sys.path.insert(0, _HELP)

import reduce as R  # noqa: E402


# --- ddmin -------------------------------------------------------------------

class TestDdmin:
    def test_finds_the_required_subsequence(self):
        """Classic case: only {3, 7} matter, everything else must go."""
        seq = list(range(10))
        got = R.ddmin(seq, lambda s: 3 in s and 7 in s)
        assert got == [3, 7]

    def test_reaches_the_empty_set(self):
        """REGRESSION: the loop stopped at len<2, so `[x]` was returned untested.

        With an always-true predicate the 1-minimal answer is the EMPTY list. Before the
        fix this returned a 1-element list, which is what split one bug into five
        clusters: `""` witnessed it, but `"d"` could never shrink to `""`.
        """
        assert R.ddmin([1, 2, 3, 4], lambda s: True) == []
        assert R.ddmin(["d"], lambda s: True) == []

    def test_keeps_a_genuinely_required_single_element(self):
        assert R.ddmin(["v"], lambda s: len(s) == 1) == ["v"]

    def test_result_is_one_minimal(self):
        """No single remaining element may be removable -- that is what 1-minimal means."""
        seq = list("abcdefgh")
        pred = lambda s: "c" in s and "f" in s          # noqa: E731
        got = R.ddmin(seq, pred)
        for i in range(len(got)):
            assert not pred(got[:i] + got[i + 1:]), f"element {got[i]!r} was removable"

    def test_empty_input(self):
        assert R.ddmin([], lambda s: True) == []

    def test_never_returns_a_non_witness(self):
        """Whatever comes back must still satisfy the predicate."""
        seq = list(range(12))
        pred = lambda s: sum(s) >= 20                    # noqa: E731
        assert pred(R.ddmin(seq, pred))


# --- pattern tokenization ----------------------------------------------------

class TestTokenizePattern:
    @pytest.mark.parametrize("pattern", [
        r"[\s\t\p{C}]",
        r"([\s\t\p{Zl}\p{C}\p{Zp}])",
        r"^.*\p{Upper}.*$",
        r"a\\b",
        r"[]]",
        r"[^]]",
        r"[a-z0-9\]]",
        r"\u{1F600}",
        r"(?<name>x)|(?<name>y)",
        r"",
    ])
    def test_round_trips(self, pattern):
        """Joining the tokens must rebuild the source EXACTLY.

        This is the invariant that keeps ddmin honest: if tokenization lost or duplicated
        a character, every candidate it built would be a different regex than intended and
        the 'reduction' would be meaningless.
        """
        assert "".join(R.tokenize_pattern(pattern)) == pattern

    def test_property_escape_is_one_token(self):
        assert r"\p{C}" in R.tokenize_pattern(r"a\p{C}b")

    def test_character_class_is_one_token(self):
        toks = R.tokenize_pattern(r"x[abc]y")
        assert toks == ["x", "[abc]", "y"]

    def test_class_containing_escaped_bracket(self):
        toks = R.tokenize_pattern(r"[a\]b]")
        assert toks == [r"[a\]b]"]


# --- character-class members -------------------------------------------------

class TestClassMembers:
    def test_simple(self):
        assert R.class_members("[abc]") == ("[", "]", ["a", "b", "c"])

    def test_negated_and_properties(self):
        prefix, suffix, members = R.class_members(r"[^\s\t\p{C}]")
        assert (prefix, suffix) == ("[^", "]")
        assert members == ["\\s", "\\t", r"\p{C}"]

    def test_range_stays_whole(self):
        """Splitting `a-z` yields `a-` or `-z`: a SyntaxError or a different language."""
        _, _, members = R.class_members(r"[a-z0-9]")
        assert "a-z" in members and "0-9" in members

    @pytest.mark.parametrize("cls", [r"[abc]", r"[^\s\t\p{C}]", r"[a-z0-9]", r"[\]]"])
    def test_round_trips(self, cls):
        prefix, suffix, members = R.class_members(cls)
        assert prefix + "".join(members) + suffix == cls

    def test_rejects_non_class(self):
        assert R.class_members("abc") is None
        assert R.class_members("") is None


# --- observation bookkeeping -------------------------------------------------

def _obs(**kw):
    return dict(kw)


class TestSignature:
    def test_agreement_is_not_a_discrepancy(self):
        obs = _obs(node="A", bun="A", deno="A")
        assert not R.is_discrepancy(obs)
        assert R.signature(obs) == (("bun", "deno", "node"),)

    def test_partition_is_canonical(self):
        obs = _obs(node="A", bun="B", deno="A")
        assert R.is_discrepancy(obs)
        assert R.signature(obs) == (("bun",), ("deno", "node"))

    def test_none_is_its_own_bucket(self):
        """A crashed/timed-out engine must never be folded into 'disagreed'."""
        obs = _obs(node="A", bun=None, deno="A")
        assert R.signature(obs) == (("bun",), ("deno", "node"))
        assert not R.is_discrepancy(obs)   # only one engine actually produced a value

    def test_three_way_split(self):
        obs = _obs(node="A", bun="B", deno="C")
        assert R.signature(obs) == (("bun",), ("deno",), ("node",))


class TestDivergingKeys:
    def test_names_the_differing_battery_entry(self):
        a = '{"ok": true, "value": {"preset_0": 1, "preset_1": 2}}'
        b = '{"ok": true, "value": {"preset_0": 1, "preset_1": 99}}'
        assert R.diverging_keys({"node": a, "deno": a, "bun": b}) == ["preset_1"]

    def test_empty_when_values_are_not_dicts(self):
        a = '{"ok": true, "value": null}'
        b = '{"ok": true, "value": {"match": "x"}}'
        assert R.diverging_keys({"node": a, "bun": b}) == []

    def test_ignores_engines_with_no_result(self):
        a = '{"ok": true, "value": {"k": 1}}'
        assert R.diverging_keys({"node": a, "bun": None}) == []


# --- reproducer rendering ----------------------------------------------------

class TestReproJs:
    def test_pins_lastindex_when_divergence_is_at_a_preset(self):
        """REGRESSION: a bare `.exec(s)` runs at lastIndex 0 and does NOT reproduce a
        divergence that only exists at lastIndex 1."""
        js = R.repro_js(("exec", ".", "gu", "ab"), ["preset_1"])
        assert "lastIndex = 1" in js
        assert "re.exec" in js

    def test_plain_form_when_no_preset_is_implicated(self):
        js = R.repro_js(("exec", "[\\s\\t\\p{C}]", "v", "x"), ["match"])
        assert "lastIndex" not in js
        assert js.startswith("new RegExp")

    def test_string_apis_render_on_the_string(self):
        assert R.repro_js(("split", "a", "", "xay"), []).startswith('"xay".split(')

    def test_preset_zero_is_still_pinned(self):
        """preset_0 is a real preset, and `0` must not be mistaken for 'no preset'."""
        js = R.repro_js(("exec", ".", "gu", "ab"), ["preset_0"])
        assert "lastIndex = 0" in js


# --- key derivation ----------------------------------------------------------

class TestKeys:
    SIG = (("bun",), ("deno", "node"))

    def test_dedup_key_separates_different_reduced_patterns(self):
        a = R.dedup_key(("exec", "[^;]", "gv", "x"), self.SIG)
        b = R.dedup_key(("exec", ".", "gv", "x"), self.SIG)
        assert a != b

    def test_mechanism_key_merges_different_patterns(self):
        """The measured need: four gv witnesses reduce to four different 1-minimal
        patterns but are one bug. Dropping the pattern collapses them."""
        keys = ["preset_1"]
        a = R.mechanism_key(("exec", "[^;]", "gv", "x"), self.SIG, keys)
        b = R.mechanism_key(("exec", ".", "gv", "y"), self.SIG, keys)
        assert a == b

    def test_mechanism_key_separates_different_partitions(self):
        other = (("deno",), ("bun", "node"))
        a = R.mechanism_key(("exec", ".", "gv", "x"), self.SIG, ["preset_1"])
        b = R.mechanism_key(("exec", ".", "gv", "x"), other, ["preset_1"])
        assert a != b

    def test_mechanism_key_separates_different_diverging_keys(self):
        a = R.mechanism_key(("exec", ".", "v", "x"), self.SIG, ["match"])
        b = R.mechanism_key(("exec", ".", "v", "x"), self.SIG, ["preset_1"])
        assert a != b

    def test_dedup_key_ignores_the_input(self):
        """The input is the witness, not the mechanism."""
        a = R.dedup_key(("exec", ".", "gv", "aaaa"), self.SIG)
        b = R.dedup_key(("exec", ".", "gv", "zzzz"), self.SIG)
        assert a == b
