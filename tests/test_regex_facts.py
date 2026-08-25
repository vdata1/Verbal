"""Unit tests for pipeline.regex_facts -- per-regex analysis (anchoring + flags).

conftest.py puts ``src`` on the path. These are pure/structural (no Fandango).
"""

import pytest

from pipeline.regex_facts import (
    analyze, RegexFacts, effective_flags, variant_flag_sets, _requires_u,
    js_construction_flags,
)


# --- anchored_single_match (moved from specialize; matches at most once) ------

class TestAnchoredSingleMatch:
    @pytest.mark.parametrize("pat", [
        r"^(\w+:)?tape-record-admin$",   # both ends
        r"^GRID_PPEM",                   # start only
        r"a$",                           # end only
        r"(^http(s)?://.+?/).*",         # ^ inside leading subpattern
        r"^a|^b",                        # every branch start-anchored
    ])
    def test_positive(self, pat):
        assert analyze(pat).anchored_single_match is True

    @pytest.mark.parametrize("pat", [
        r"abc",                          # no anchor
        r"a|b$",                         # only one branch end-anchored -> can repeat via `a`
        r".*?/projects/(.*?)/zones",     # unanchored
        r"\bword\b",                     # word boundaries are not start/end anchors
        r"\A= Action Pack",              # \A is a JS literal "A", NOT a start anchor
        r"(^\s*>.*\n){2,}\s*\Z",         # \Z is a JS literal "Z"; leading `^` is inside a repeat
    ])
    def test_negative(self, pat):
        assert analyze(pat).anchored_single_match is False


# --- requires_flags: m -------------------------------------------------------

class TestRequiresM:
    @pytest.mark.parametrize("pat", [
        r"(^\s*>.*\n){2,}\s*\Z",   # ^ at start of a {2,} body (line boundary from \n)
        r"(^a\n){2}",              # ^ inside a forced repeat, satisfiable with m
        # --- cross-boundary newline-pinned anchors (P3.7) ---
        r"(^.*$)\n(^ +return)",    # regex_246: $ before \n (more required), ^ after \n
        r"a$\nb",                  # $ then required \n then required b -> non-final \n
        r"(a$)\n(^b)",             # $ ends a group, \n outside, ^ starts next group
    ])
    def test_requires_m(self, pat):
        assert "m" in analyze(pat).requires_flags

    @pytest.mark.parametrize("pat", [
        r"^abc$",                  # anchors only at boundaries -> satisfiable without m
        r"a$",                     # trailing $ , nothing required after
        r"a$b?",                   # optional after $ -> not forced -> no m
        r"\A= Action Pack",        # \A is m-insensitive
        r"(^a){1,3}",              # min=1 -> can match once without m
        r"_$foreign_id$",          # unsatisfiable (see below), NOT rescued by m
        r"a$\n",                   # $ before a FINAL \n -> matches without m (no content after)
        r"(a$\nb)|c",              # only one branch is newline-pinned -> c matches w/o m
    ])
    def test_no_m(self, pat):
        assert "m" not in analyze(pat).requires_flags


class TestUnsatisfiableInternalAnchor:
    @pytest.mark.parametrize("pat", [
        r"_$foreign_id$",          # $ then literal f -> matches nothing
        r"\A ( $pattern ) \z",     # $ then literal p (inside a required group)
        r"\$\Q$k\E",               # normalizes to ...$kE -> $ then literal k
        r"(x$y){2}",               # $ then literal y inside a required repeat
        r"a$b",                    # simplest case
        # --- every-alternative-unsatisfiable BRANCH (P3.7) ---
        r"a$b|c$d",                # BOTH branches are $-then-literal -> whole unsat
        r"^ @?$x|, @?$y|; @?$z",   # regex_2068 shape: all 3 branches have $ then literal
    ])
    def test_flagged(self, pat):
        assert analyze(pat).unsatisfiable_internal_anchor is True

    @pytest.mark.parametrize("pat", [
        r"a$",                     # boundary $ -> satisfiable
        r"^abc$",                  # boundary anchors
        r"(a$b)|c",                # unsat alternative, but `c` matches -> NOT flagged
        r"a$b|cd",                 # 2nd branch has no bad anchor -> NOT flagged
        r"(a$b)?d",                # optional group -> NOT flagged
        r"a$\nb",                  # $ then \n -> the newline supplies the boundary
        r"foo$",                   # trailing $
        r"x$|y",                   # branch with a satisfiable alternative
        r"a\Zb",                   # \Z is a JS literal Z, not an anchor
        r"(^\s*>.*\n){2,}\s*\Z",   # requires-m, but satisfiable (not unsatisfiable)
    ])
    def test_not_flagged(self, pat):
        assert analyze(pat).unsatisfiable_internal_anchor is False


# --- requires_flags: u -------------------------------------------------------

class TestRequiresU:
    def test_braced_codepoint_requires_u(self):
        assert "u" in analyze(r"\u{1D306}").requires_flags

    def test_braced_range_requires_u(self):
        assert "u" in analyze(r"[\u{11EE0}-\u{11EF8}]").requires_flags

    def test_escaped_backslash_not_u(self):
        # Two backslashes then u{ : an escaped backslash, NOT a \u{} escape.
        assert _requires_u("\\\\u{1D306}") is False

    def test_plain_u_escape_not_braced(self):
        # A (4-hex, no brace) is valid without the u flag.
        assert "u" not in analyze(r"A").requires_flags


# --- effective_flags + meta round-trip ---------------------------------------

def test_effective_flags_union_and_order():
    # matchAll's g + a regex requiring u,m -> canonical gimsuy order.
    assert effective_flags("g", frozenset({"u", "m"})) == "gmu"
    assert effective_flags("", frozenset()) == ""
    assert effective_flags("g", frozenset()) == "g"


def test_meta_roundtrip():
    f = RegexFacts(anchored_single_match=True, requires_flags=frozenset({"m", "u"}))
    assert RegexFacts.from_meta(f.to_meta()) == f


class TestVariantFlagSets:
    def test_base_always_first_and_present(self):
        # Even if config omits "", the required-only base is variant[0].
        v = variant_flag_sets("g", frozenset(), ["i", "m"])
        assert v[0] == "g" and "g" in v

    def test_optional_flags_union_onto_base(self):
        assert variant_flag_sets("", frozenset(), ["", "i", "m", "s"]) == ["", "i", "m", "s"]
        assert variant_flag_sets("g", frozenset(), ["", "i", "m", "s"]) == ["g", "gi", "gm", "gs"]

    def test_required_flags_never_dropped(self):
        # A requires-u regex always carries u across every variant.
        v = variant_flag_sets("", frozenset({"u"}), ["", "i", "m"])
        assert all("u" in x for x in v)

    def test_dedup_when_modifier_already_required(self):
        # base gm + modifier "m" collapses to gm (no duplicate variant).
        v = variant_flag_sets("g", frozenset({"m"}), ["", "i", "m", "s"])
        assert v == ["gm", "gim", "gms"]

    def test_canonical_order(self):
        # Always emitted in gimsuy order regardless of how requested.
        assert variant_flag_sets("", frozenset(), ["si", "mi"]) == ["", "is", "im"]


class TestUnicodeSetsSupersedesU:
    """`v` (unicodeSets) is the ONE modifier that displaces a required flag.

    `u` and `v` together are a SyntaxError on every engine, and `v` is a strict
    superset of `u`, so `v` wins. This is load-bearing rather than cosmetic: `u` is
    required exactly for the `\\p{...}` / `\\u{...}` patterns that `v` is interesting
    on, so a plain union would turn the whole `v` axis into a SyntaxError all three
    engines agree on -- maximum cost, zero signal, indistinguishable from coverage.
    """

    def test_uv_never_coexist(self):
        for got in (variant_flag_sets("", frozenset({"u"}), ["", "v"]),
                    variant_flag_sets("g", frozenset({"u"}), ["", "i", "v"]),
                    variant_flag_sets("", frozenset({"u", "m"}), ["", "v", "d"])):
            assert not any("u" in f and "v" in f for f in got), got

    def test_v_variant_reachable_on_a_requires_u_pattern(self):
        # The point of the rule: the \p{...} pattern still GETS a v harness.
        got = variant_flag_sets("", frozenset({"u"}), ["", "i", "v"])
        assert "v" in got, got

    def test_v_preserves_other_required_flags(self):
        # Only `u` is displaced -- matchAll's mandatory g survives.
        got = variant_flag_sets("g", frozenset({"u"}), ["v"])
        assert "gv" in got, got

    def test_v_is_pure_addition_when_u_not_required(self):
        assert variant_flag_sets("", frozenset(), ["", "v"]) == ["", "v"]

    def test_canonical_position_of_v(self):
        # .flags-getter order is d g i m s u v y, so v sits between u and y.
        assert effective_flags("", frozenset({"v", "d", "y"})) == "dvy"
        assert effective_flags("", frozenset({"u", "d", "y"})) == "duy"

    def test_construction_gate_ignores_v(self):
        # v is stricter than u and never required, so gating on it would exclude
        # patterns that are valid under the flags they actually need (over-correcting
        # EXPERIMENT_GAPS G1). A v harness that cannot construct is a comparable
        # SyntaxError outcome instead.
        assert js_construction_flags(r"[\p{L}]+") == "u"
        assert js_construction_flags(r"[a-z,]+") == ""
