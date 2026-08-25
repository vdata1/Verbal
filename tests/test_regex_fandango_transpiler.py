r"""Unit tests for the regex -> Fandango transpiler, focused on the three
mis-compilation fixes (2026-07-07) plus regression coverage for the char-class
and category paths they touch.

Two layers:

* Fast transpiler-only tests assert on the emitted ``.fan`` text (no Fandango).
* A handful of Fandango-backed *semantic* tests fuzz the emitted grammar and
  check the generated strings actually match the source regex under Python
  ``re`` -- these are the real guards that each fix produces matching data, not
  just plausible-looking grammar. They use small, seeded budgets.

Run: ``pytest tests/test_regex_fandango_transpiler.py`` (conftest puts src on path).
"""

import re

import pytest

from regex_fandango_transpiler import (
    RegexToFandangoTranslator,
    rewrite_js_codepoint_escapes,
    rewrite_js_identity_escapes,
    normalize_js_regex,
    ANY_CHAR,
    DOT_CHAR,
)


def transpile(regex: str) -> str:
    """Return the base ``.fan`` content for a regex (constraints included)."""
    fan, _ = RegexToFandangoTranslator().generate_ebnf_grammar_with_constraints(regex)
    return fan


def fuzz_strings(regex: str, n: int = 20, seed: int = 0) -> list[str]:
    """Fuzz the transpiled grammar for a regex; return distinct string values."""
    import fandango

    fan = transpile(regex)
    inst = fandango.Fandango(fan, use_cache=False)
    return [str(x) for x in inst.fuzz(desired_solutions=n, max_generations=80, random_seed=seed)]


# ---------------------------------------------------------------------------
# Bug 1: JS \u{...} code-point escapes
# ---------------------------------------------------------------------------

class TestCodepointEscapeRewrite:
    def test_astral_escape_becomes_padded_U(self):
        assert rewrite_js_codepoint_escapes(r"\u{1D306}") == r"\U0001D306"

    def test_short_escape_zero_padded(self):
        assert rewrite_js_codepoint_escapes(r"\u{41}") == r"\U00000041"

    def test_in_class_range_endpoints_rewritten(self):
        assert (
            rewrite_js_codepoint_escapes(r"[\u{11EE0}-\u{11EF8}]")
            == r"[\U00011EE0-\U00011EF8]"
        )

    def test_multiple_escapes_in_one_pattern(self):
        assert rewrite_js_codepoint_escapes(r"a\u{41}b\u{42}") == r"a\U00000041b\U00000042"

    def test_escaped_backslash_not_treated_as_escape(self):
        # \\u{41} is a literal backslash then u{41}; must be left untouched.
        assert rewrite_js_codepoint_escapes(r"\\u{41}") == r"\\u{41}"

    def test_non_hex_contents_untouched(self):
        # A regex that literally matches \u{...} syntax -- contents are not hex.
        pat = r"\u{[0-9a-fA-F]{1,6}}"
        assert rewrite_js_codepoint_escapes(pat) == pat

    def test_empty_braces_untouched(self):
        assert rewrite_js_codepoint_escapes(r"\u{}") == r"\u{}"

    def test_bmp_four_hex_escape_untouched(self):
        # \uD834 is the Python-native 4-hex form; not our concern, leave it.
        assert rewrite_js_codepoint_escapes(r"\uD834") == r"\uD834"

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            rewrite_js_codepoint_escapes(r"\u{110000}")

    def test_transpiles_without_crash_and_emits_literal(self):
        fan = transpile(r"\u{1D306}")
        assert chr(0x1D306) in fan  # the astral char landed as a grammar literal

    # --- braced \x{...} (Perl/PCRE spelling; same code-point reading as \u{}) ---

    def test_braced_x_becomes_padded_U(self):
        assert rewrite_js_codepoint_escapes(r"\x{e1}") == r"\U000000E1"

    def test_braced_x_astral(self):
        assert rewrite_js_codepoint_escapes(r"\x{1D306}") == r"\U0001D306"

    def test_braced_x_in_class_range(self):
        assert (
            rewrite_js_codepoint_escapes(r"[\x{1094}-\x{1095}]")
            == r"[\U00001094-\U00001095]"
        )

    def test_two_hex_x_escape_untouched(self):
        # \xe1 is the Python-native 2-hex form; not a braced escape, leave it.
        assert rewrite_js_codepoint_escapes(r"\xe1") == r"\xe1"

    def test_braced_x_escaped_backslash_untouched(self):
        assert rewrite_js_codepoint_escapes(r"\\x{e1}") == r"\\x{e1}"

    def test_braced_x_out_of_range_raises(self):
        with pytest.raises(ValueError):
            rewrite_js_codepoint_escapes(r"\x{110000}")

    @pytest.mark.parametrize("pat", [
        r"\x{0637}",        # regex_673
        r"\x{A0}+",          # regex_740
        r"(\x{1094}|\x{1095})",  # regex_1215
    ])
    def test_braced_x_previously_failing_now_transpile(self, pat):
        fan = transpile(pat)              # must not raise (\x{ was incomplete escape)
        assert "<start> ::=" in fan


# ---------------------------------------------------------------------------
# Bug: \A \Z \z are Perl/Python anchors but JS IDENTITY escapes (literal letters)
# ---------------------------------------------------------------------------

class TestPerlAnchorRewrite:
    def test_uppercase_A_becomes_literal(self):
        assert rewrite_js_identity_escapes(r"\A= Action Pack") == r"A= Action Pack"

    def test_uppercase_Z_becomes_literal(self):
        assert rewrite_js_identity_escapes(r"a\Zb") == r"aZb"

    def test_lowercase_z_becomes_literal(self):
        # Python re rejects \z outright; JS reads it as literal "z".
        assert rewrite_js_identity_escapes(r"x\zy") == r"xzy"

    def test_all_three_together(self):
        assert rewrite_js_identity_escapes(r"\A\Z\z") == r"AZz"

    def test_escaped_backslash_left_alone(self):
        # \\A is an escaped backslash then A; not an identity-escape anchor.
        assert rewrite_js_identity_escapes(r"\\A") == r"\\A"

    def test_other_escapes_untouched(self):
        assert rewrite_js_identity_escapes(r"\d\w\bfoo") == r"\d\w\bfoo"

    def test_perl_QEG_become_literals(self):
        # \Q \E \G are Perl idioms; JS reads each as the bare letter, and \Q..\E is
        # NOT quoting (content between is parsed normally).
        assert rewrite_js_identity_escapes(r"\Qa\E") == r"QaE"
        assert rewrite_js_identity_escapes(r"\G(a)") == r"G(a)"

    def test_e_and_K_become_literals(self):
        # JS reads \e as literal "e" (NOT ESC 0x1B) and \K as literal "K" (no Perl \K).
        assert rewrite_js_identity_escapes(r"\e\[31m") == r"e\[31m"
        assert rewrite_js_identity_escapes(r"a\Kb") == r"aKb"

    @pytest.mark.parametrize("pat", [
        r"\$\Q$k\E",              # regex_18: \Q \E previously errored
        r"\G([ ]{4}|\t).*$\n?",    # regex_30: \G previously errored
    ])
    def test_perl_idioms_now_transpile(self, pat):
        fan = transpile(pat)      # must not raise
        assert "<start> ::=" in fan

    # -- Semantic parity: the oracle must read \A \Z \z as LITERAL letters, not
    # zero-width anchors. This guards the historical bug where the neutral oracle
    # (Python `re` on the normalized pattern) treated \Z as an end anchor and so
    # OVERSTATED matching -- reporting a match on strings the JS engines reject.
    # A literal reading matches "...Z" only; an anchor reading would spuriously
    # match the empty end of ANY string. The two readings disagree exactly here,
    # so these asserts fail loudly if the normalize step is ever dropped.
    @pytest.mark.parametrize("pat, hit, miss", [
        (r"a\Z", "aZ", "a"),   # anchor reading of \Z would match "a" at end; literal must not
        (r"\Ab", "Ab", "b"),   # anchor reading of \A would match "b" at start; literal must not
        (r"x\zy", "xzy", "xy"),
    ])
    def test_oracle_reads_perl_anchors_as_literals(self, pat, hit, miss):
        oracle = re.compile(normalize_js_regex(pat))  # same path generate.py's oracle uses
        assert oracle.search(hit), f"{pat!r} should match {hit!r} (literal reading)"
        assert not oracle.search(miss), (
            f"{pat!r} matched {miss!r}: \\A/\\Z/\\z read as an anchor, not a literal"
        )

    def test_fuzzed_strings_carry_the_literal_letter(self):
        # End-to-end guard: the grammar for a \Z pattern must GENERATE the literal
        # "Z", and every fuzzed string must match the source regex under the oracle.
        pat = r"foo\Zbar"
        oracle = re.compile(normalize_js_regex(pat))
        strings = fuzz_strings(pat, n=5)
        assert strings, "grammar produced no strings"
        for s in strings:
            assert "Z" in s, f"generated string dropped the literal Z: {s!r}"
            assert oracle.fullmatch(s), f"generated string does not match /{pat}/: {s!r}"

    def test_normalize_composes_both_rewrites(self):
        assert normalize_js_regex(r"\u{1D306}\Z") == r"\U0001D306Z"

    @pytest.mark.parametrize("pat", [
        r"\A([0-9a-zA-Z\.\/\-_]+): (.*)\z",   # regex_15: \z previously errored
        r"\A.*(passwor[dt]|_pwd?).*\z",        # regex_80
        r"\A= Action Pack",                    # regex_37
    ])
    def test_previously_failing_now_transpile(self, pat):
        fan = transpile(pat)          # must not raise (\z used to be a bad escape)
        assert "<start> ::=" in fan

    def test_Z_lands_as_literal_in_grammar(self):
        # A trailing \Z must appear as a literal "Z" the engine will require.
        fan = transpile(r"end\Z")
        assert '"Z"' in fan


# ---------------------------------------------------------------------------
# JS control escapes \cX: \c + letter -> control char (code & 0x1F); \c + non-letter
# -> Annex-B literal backslash + "c". (\e/\K live in the identity-escape block.)
# ---------------------------------------------------------------------------

from regex_fandango_transpiler import rewrite_js_control_escapes


class TestControlEscapeRewrite:
    def test_letter_maps_to_control_char(self):
        # \cM -> CR (0x0D), \cJ -> LF (0x0A), emitted as \xHH for sre_parse.
        assert rewrite_js_control_escapes(r"\cM") == r"\x0D"
        assert rewrite_js_control_escapes(r"\cJ") == r"\x0A"

    def test_case_insensitive_control(self):
        # \ca and \cA are both 0x01 (code & 0x1F).
        assert rewrite_js_control_escapes(r"\ca") == r"\x01"
        assert rewrite_js_control_escapes(r"\cA") == r"\x01"

    def test_nonletter_is_annexb_literal(self):
        # \c@ is literal backslash + "c" (then the non-letter stays); -> \\c@.
        assert rewrite_js_control_escapes(r"\c@") == r"\\c@"

    def test_control_in_class(self):
        # Same reading inside a char class ([\cJ] is an LF member).
        assert rewrite_js_control_escapes(r"[\cJ]") == r"[\x0A]"
        assert rewrite_js_control_escapes(r"[^\c@]") == r"[^\\c@]"

    def test_escaped_backslash_not_control(self):
        # \\cM is an escaped backslash + literal "cM"; must be untouched.
        assert rewrite_js_control_escapes(r"\\cM") == r"\\cM"

    @pytest.mark.parametrize("pat", [
        r"(\cM\cJ|\cM|\cJ)",             # regex_1853
        r"([^\cJ]+)(\cJ[^\c@]*|)\c@",    # regex_2112 (control + annex-b literal)
        r"\e\[1mindex",                   # regex_745 (\e literal)
        r"$prefix\K\b$regex\b",           # regex_317 (\K literal)
    ])
    def test_previously_failing_now_transpile(self, pat):
        fan = transpile(pat)          # must not raise (\c/\e/\K were bad escapes)
        assert "<start> ::=" in fan

    def test_semantic_control_range_matches(self):
        # \cJ must generate LF-containing strings that match the source under re.
        strings = fuzz_strings(r"a\cJb", n=8)
        assert strings
        pat = re.compile(normalize_js_regex(r"a\cJb"))
        assert all(pat.search(s) for s in strings), [repr(s) for s in strings]


# ---------------------------------------------------------------------------
# JS named groups (?<name>...) / backrefs \k<name>: Python's sre_parse wants the
# (?P<name>...) / (?P=name) spelling. Pure syntax translation (same group numbers).
# ---------------------------------------------------------------------------

from regex_fandango_transpiler import rewrite_js_named_groups


class TestNamedGroupRewrite:
    def test_named_group_to_python_spelling(self):
        assert rewrite_js_named_groups(r"(?<year>\d{4})") == r"(?P<year>\d{4})"

    def test_named_backref_to_python_spelling(self):
        assert rewrite_js_named_groups(r"(?<y>\d)-\k<y>") == r"(?P<y>\d)-(?P=y)"

    def test_nested_named_groups(self):
        assert (
            rewrite_js_named_groups(r"(?<a>x|(?<b>y))")
            == r"(?P<a>x|(?P<b>y))"
        )

    @pytest.mark.parametrize("pat", [r"(?<=a)b", r"(?<!a)b"])
    def test_lookbehind_left_alone(self, pat):
        # (?<= and (?<! are lookbehind, NOT named groups -- must not be rewritten.
        assert rewrite_js_named_groups(pat) == pat

    def test_group_syntax_inside_char_class_is_literal(self):
        # Inside [...], `(?<` and `\k<` are literal characters, never group syntax.
        assert rewrite_js_named_groups(r"[(?<x>]") == r"[(?<x>]"
        assert rewrite_js_named_groups(r"[\k<x>]") == r"[\k<x>]"

    def test_leading_bracket_member_then_named_group(self):
        # A leading `]` (optionally after ^) is a class member, not a close; the
        # named group AFTER the class must still be rewritten.
        assert rewrite_js_named_groups(r"[]](?<n>a)") == r"[]](?P<n>a)"
        assert rewrite_js_named_groups(r"[^]](?<n>a)") == r"[^]](?P<n>a)"

    def test_escaped_backslash_before_k_left_alone(self):
        # \\k<x> is an escaped backslash + literal k, NOT a named backreference.
        assert rewrite_js_named_groups(r"\\k<x>") == r"\\k<x>"

    @pytest.mark.parametrize("pat", [
        r"^.+-(?<locale>\w+).yml$",                       # regex_268
        r"(?<_1>.|(?<_2>\\.))\-(?<_3>[^\]]|(?<_4>\\.))",   # regex_110 (nested)
        r"^-(?<level>v+)$",                                # regex_1972
        r"^(?<prefix>[+-]?)(?<numeric_part>\d{3,}\.\d{1})(?<suffix>%)$",  # regex_1481
    ])
    def test_previously_failing_now_transpile(self, pat):
        fan = transpile(pat)          # must not raise (?< used to be unknown extension)
        assert "<start> ::=" in fan

    def test_semantic_named_backref_generates_matching(self):
        # A named backref must produce strings where the two groups agree.
        strings = fuzz_strings(r"(?<y>\d{4})-\k<y>", n=10)
        assert strings
        pat = re.compile(normalize_js_regex(r"(?<y>\d{4})-\k<y>"))
        assert all(pat.search(s) for s in strings), [repr(s) for s in strings]


# ---------------------------------------------------------------------------
# Unicode property escapes \p{X} / \P{X} / \pX -> EXPLICIT char sets, resolved by
# the authoritative `regex` module (exact code-point fidelity).
# ---------------------------------------------------------------------------

import regex as _regex_mod
from regex_fandango_transpiler import (
    rewrite_js_unicode_properties, UnsupportedUnicodeProperty,
)


def _fidelity_diff(regex_frag: str, property_token: str, hi: int = 0x110000) -> list:
    """Code points where our emitted char set and `regex`'s \\p{token} disagree."""
    ours = re.compile(regex_frag)
    ref = _regex_mod.compile("\\p{" + property_token + "}")
    return [cp for cp in range(hi)
            if bool(ours.fullmatch(chr(cp))) != bool(ref.match(chr(cp)))]


class TestUnicodePropertyRewrite:
    @pytest.mark.parametrize("token", [
        "L", "Ll", "N", "Pc", "Pd", "Zs", "Alnum", "Alpha",
        "InCJKUnifiedIdeographs", "katakana", "sc=Adlm", "scx=Adlm",
    ])
    def test_positive_char_set_is_exact(self, token):
        # \p{token} outside a class -> [ranges] matching EXACTLY the property.
        diff = _fidelity_diff(rewrite_js_unicode_properties("\\p{" + token + "}"), token)
        assert not diff, f"\\p{{{token}}} diverges on {len(diff)} cps, first {diff[:3]}"

    def test_negated_outside_class_is_complement(self):
        # \P{L} outside a class -> [^...] must match EXACTLY the non-letters.
        ours = re.compile(rewrite_js_unicode_properties(r"\P{L}"))
        ref = _regex_mod.compile(r"\P{L}")
        bad = [cp for cp in range(0x3000)
               if bool(ours.fullmatch(chr(cp))) != bool(ref.match(chr(cp)))]
        assert not bad, bad[:3]

    def test_single_letter_form(self):
        # \pL == \p{L}, \PN == \P{N}
        assert rewrite_js_unicode_properties(r"\pL") == rewrite_js_unicode_properties(r"\p{L}")
        assert rewrite_js_unicode_properties(r"\PN") == rewrite_js_unicode_properties(r"\P{N}")

    def test_in_class_splice_positive(self):
        # [\p{Pd}\p{Pc}] must match exactly the union of the two properties.
        frag = rewrite_js_unicode_properties(r"[\p{Pd}\p{Pc}]")
        ours = re.compile(frag)
        ref = _regex_mod.compile(r"[\p{Pd}\p{Pc}]")
        bad = [cp for cp in range(0x110000)
               if bool(ours.fullmatch(chr(cp))) != bool(ref.match(chr(cp)))]
        assert not bad, bad[:3]

    def test_in_class_splice_negated_complement(self):
        # [\P{Ll}x] == (not-Ll) or x -- the negated property splices its complement.
        frag = rewrite_js_unicode_properties(r"[\P{Ll}x]")
        ours = re.compile(frag)
        ref = _regex_mod.compile(r"[\P{Ll}x]")
        bad = [cp for cp in range(0x3000)
               if bool(ours.fullmatch(chr(cp))) != bool(ref.fullmatch(chr(cp)))]
        assert not bad, bad[:3]

    def test_escaped_backslash_not_a_property(self):
        # \\p{L} is an escaped backslash + literal p{L}; must be left untouched.
        assert rewrite_js_unicode_properties(r"\\p{L}") == r"\\p{L}"

    def test_unknown_property_raises_typed(self):
        with pytest.raises(UnsupportedUnicodeProperty) as ei:
            rewrite_js_unicode_properties(r"\p{NotARealProperty}")
        assert ei.value.token == "NotARealProperty"

    @pytest.mark.parametrize("pat", [
        r"^\p{Alpha}{3}",                      # regex_2645
        r"^(\p{Ll})",                          # regex_1071
        r"[Rr]ead(?:\p{Zs}*|[\p{Pd}\p{Pc}])?", # regex_281 (in-class + outside)
        r"^(\p{InCJKUnifiedIdeographs}+)",      # regex_1489 (block)
        r"\pN",                                 # regex_293 (single-letter)
    ])
    def test_previously_failing_now_transpile(self, pat):
        fan = transpile(pat)          # must not raise (\p was unsupported in sre_parse)
        assert "<start> ::=" in fan

    def test_semantic_generated_chars_match_property(self):
        # Fuzzed strings for a property regex must actually match it.
        strings = fuzz_strings(r"^\p{Ll}{2}$", n=10)
        assert strings
        pat = re.compile(normalize_js_regex(r"^\p{Ll}{2}$"))
        assert all(pat.fullmatch(s) for s in strings), [repr(s) for s in strings]


# ---------------------------------------------------------------------------
# Bug: a LITERAL - / ^ / ] inside [...] must be escaped, not reinterpreted as a
# range operator / negation / class-close.
# ---------------------------------------------------------------------------

def _emitted_class(pat: str) -> str:
    """The r'[...]' body the transpiler emits for a single-class regex."""
    fan = transpile(pat)
    line = next(l for l in fan.splitlines() if "r'[" in l)
    return line.split("r'", 1)[1].rsplit("'", 1)[0]


class TestClassLiteralEscaping:
    @pytest.mark.parametrize("pat", [
        r"[a\-z]",                 # {a,-,z}, NOT the range a-z
        r"[0-9a-zA-Z\.\/\-_]",     # regex_15's class
        r"[a-c\-x]",               # a genuine range PLUS a literal hyphen
        r"[-a]",                   # leading hyphen is literal
        r"[a-]",                   # trailing hyphen is literal
        r"[\^a]",                  # literal caret member (not negation)
        r"[a\]b]",                 # literal ] member (not class close)
        r"[\^\-\]]",               # all three metacharacters as literals
        r"[a-z]",                  # a genuine range must STILL be a range
    ])
    def test_emitted_class_membership_matches_source(self, pat):
        # The emitted terminal must accept EXACTLY the same ASCII chars as the
        # source class does under Python re.
        src = re.compile(pat)
        emit = re.compile(_emitted_class(pat))
        diff = [chr(c) for c in range(128)
                if bool(src.fullmatch(chr(c))) != bool(emit.fullmatch(chr(c)))]
        assert not diff, f"{pat!r} -> {_emitted_class(pat)!r} diverges on {diff}"

    def test_escaped_hyphen_is_not_a_range(self):
        # The reported bug: [a\-z] must not become the range [a-z].
        emit = _emitted_class(r"[a\-z]")
        assert not re.compile(emit).fullmatch("b")

    def test_genuine_range_preserved(self):
        assert re.compile(_emitted_class(r"[a-z]")).fullmatch("m")

    def test_semantic_astral_char_generated(self):
        strings = fuzz_strings(r"\u{1D306}", n=1)
        assert strings and all(s == chr(0x1D306) for s in strings)


# ---------------------------------------------------------------------------
# Bug 2: negated-category char classes ([\s\S] and friends)
# ---------------------------------------------------------------------------

class TestNegatedCategoryClasses:
    def test_s_S_union_is_alternation_not_inline_caret(self):
        fan = transpile(r"[\s\S]")
        assert r"(r'[ \t\n\r\f\v]' | r'[^ \t\n\r\f\v]')" in fan
        # The old bug inlined a stray ^ mid-class; make sure that's gone.
        assert r"[ \t\n\r\f\v^" not in fan

    def test_order_independent_S_s(self):
        fan = transpile(r"[\S\s]")
        assert r"r'[^ \t\n\r\f\v]'" in fan and r"r'[ \t\n\r\f\v]'" in fan

    def test_negated_digit_shorthand_alone(self):
        fan = transpile(r"[\D]")
        assert r"r'[^0-9]'" in fan

    def test_negated_word_shorthand_alone(self):
        fan = transpile(r"[\W]")
        assert r"r'[^a-zA-Z0-9_]'" in fan

    def test_mixed_literal_and_negated_category(self):
        fan = transpile(r"[a\D]")
        assert r"(r'[a]' | r'[^0-9]')" in fan

    def test_positive_shorthand_unchanged(self):
        assert r"r'[0-9]'" in transpile(r"\d")
        assert r"r'[a-zA-Z0-9_]'" in transpile(r"\w")
        assert r"r'[ \t\n\r\f\v]'" in transpile(r"\s")

    def test_overall_negation_with_positive_items_ok(self):
        # [^\d] is emitted as a POSITIVE complement over the transpiler's ASCII
        # universe ([\x00-\x7f]), NOT r'[^0-9]': exrex samples a negated class only
        # from printable ASCII, so relying on it is unreliable (see regex_765). The
        # complement of the digits 0x30-0x39 is [\x00-\x2f\x3a-\x7f].
        fan = transpile(r"[^\d]")
        # Complement of the digits 0x30-0x39 over [\x00-\x7f]. Printable endpoints
        # render as themselves (0x2f='/', 0x3a=':'); the -/^/] specials would be
        # hex-escaped (see _codepoint_repr) but none occur here.
        assert r"r'[\x00-/:-\x7f]'" in fan
        assert "r'[^" not in fan  # no exrex-negated class terminal emitted
        # And every generated single char is a non-digit ASCII code unit.
        for s in fuzz_strings(r"[^\d]", n=30):
            assert len(s) == 1 and ord(s) < 0x80 and not s.isdigit()

    def test_plain_class_regression(self):
        assert r"r'[abc]'" in transpile(r"[abc]")
        assert r"r'[a-z]'" in transpile(r"[a-z]")
        # An overall-negated positive class becomes a positive ASCII complement
        # (exrex-safe), not r'[^abc]'. Assert the semantics rather than the exact
        # rendering: no negated class emitted, and generated chars exclude a/b/c.
        neg = transpile(r"[^abc]")
        assert "r'[^" not in neg
        for s in fuzz_strings(r"[^abc]", n=30):
            assert len(s) == 1 and ord(s) < 0x80 and s not in "abc"

    def test_negated_class_excluding_all_printable_ascii(self):
        # regex_765: [^\x09-\x7f] excludes ALL of exrex's printable-ASCII negation
        # universe, so r'[^...]' would draw from an empty pool (IndexError at fuzz
        # time). We emit the explicit low-control complement over [\x00-\x7f].
        fan = transpile(r"[^\x09-\x7f]")
        assert r"r'[\x00-\x08]'" in fan
        assert "r'[^" not in fan
        got = fuzz_strings(r"[^\x09-\x7f]", n=10)
        assert got and all(len(s) == 1 and ord(s) <= 0x08 for s in got)

    def test_complement_escapes_class_special_singletons(self):
        # A complement can isolate ] ^ - as lone members; emitted raw they corrupt
        # the class, so they must be hex-escaped. [^\\\^] excludes 0x5c and 0x5e,
        # isolating 0x5d (]) as a singleton in the complement -> must be \x5d.
        fan = transpile(r"[^\\\^]")
        assert r"\x5d" in fan and "]']" not in fan.replace(r"\x5d", "")
        for s in fuzz_strings(r"[^\\\^]", n=20):
            assert len(s) == 1 and s not in "\\^"

    def test_negated_class_complement_uses_re_oracle_semantics(self):
        # The complement is computed with Python re (the generation oracle), NOT the
        # transpiler's narrower \s table: re's \s matches \x1c-\x1f, so [^\s...] must
        # not emit them. Every generated char must match the class under re.
        pat = r"[^a-zA-Z0-9\s@_.]"
        rx = re.compile(pat)
        got = fuzz_strings(pat, n=40)
        assert got and all(rx.match(s) for s in got)

    def test_semantic_anychar_spread(self):
        # [\s\S] must generate a broad spread of single characters (any char).
        strings = fuzz_strings(r"[\s\S]", n=40)
        assert all(len(s) == 1 for s in strings)
        kinds = {("space" if s.isspace() else "alpha" if s.isalpha()
                  else "digit" if s.isdigit() else "other") for s in strings}
        # Should not collapse to only whitespace (the pre-fix Fandango behavior).
        assert len(kinds) >= 3, kinds


# ---------------------------------------------------------------------------
# Bug 2, deferred sub-case: overall negation + negated shorthand = set
# INTERSECTION ([^\S\n] = whitespace minus newlines). Computed at transpile
# time from the transpiler's own category table (see july-7 handoff).
# ---------------------------------------------------------------------------

def _emitted_class_members(regex: str) -> set:
    """Parse the single ``r'[...]'`` a class-only regex transpiles to and return
    the ASCII code points it matches (ground-truth via Python ``re`` on the
    explicit emitted body -- no shorthand semantics involved)."""
    fan = transpile(regex)
    m = re.search(r"r'(\[.*?\])'", fan)
    assert m, f"no r'[...]' class emitted for {regex!r}:\n{fan}"
    cls = re.compile(m.group(1))
    return {cp for cp in range(128) if cls.match(chr(cp))}


class TestNegatedShorthandIntersection:
    # The dominant real idioms plus the two double-negation letter cases, each
    # checked against the hand-computed set from the handoff.
    WORKED = {
        r"[^\S\n]": {0x09, 0x0b, 0x0c, 0x0d, 0x20},               # \s - {\n}
        r"[^\S\n\r]": {0x09, 0x0b, 0x0c, 0x20},                   # \s - {\n,\r}
        r"[^\n\S]": {0x09, 0x0b, 0x0c, 0x0d, 0x20},               # order-independent
        r"[^\W\d]": set(range(65, 91)) | set(range(97, 123)) | {0x5f},  # \w - \d = letters+_
        r"[^\W_]": set(range(48, 58)) | set(range(65, 91)) | set(range(97, 123)),  # \w - {_}
    }

    @pytest.mark.parametrize("regex, expected", WORKED.items())
    def test_emits_correct_finite_set(self, regex, expected):
        assert _emitted_class_members(regex) == expected

    @pytest.mark.parametrize("regex, expected", WORKED.items())
    def test_emitted_chars_match_source_regex(self, regex, expected):
        # Every character the emitted class can produce must match the ORIGINAL
        # regex under Python re (transpiler set is a subset of re's, so all match).
        src = re.compile(regex)
        assert all(src.match(chr(cp)) for cp in _emitted_class_members(regex))

    def test_computed_from_table_not_python_re(self):
        # The transpiler models \s as 6 chars; Python re's \s over ASCII also
        # matches \x1c-\x1f. [^\S\n] must follow the TABLE (exclude \x1c-\x1f),
        # otherwise it would disagree with every other \s in the codebase.
        assert not (_emitted_class_members(r"[^\S\n]") & set(range(0x1c, 0x20)))

    @pytest.mark.parametrize("regex", [r"[^\S\s]", r"[^\W\w\D\d]"])
    def test_empty_set_still_fails_loud(self, regex):
        # A class that reduces to the empty set can generate nothing -- keep the
        # narrowed raise rather than emit an unsatisfiable rule.
        with pytest.raises(NotImplementedError):
            transpile(regex)

    def test_semantic_generated_chars_match_source(self):
        # Fandango-backed: fuzz [^\S\n] and confirm every generated char is a
        # single whitespace-but-not-newline char that matches the source regex.
        strings = fuzz_strings(r"[^\S\n]", n=20)
        assert strings
        src = re.compile(r"[^\S\n]")
        assert all(len(s) == 1 and src.match(s) for s in strings), [repr(s) for s in strings]


# ---------------------------------------------------------------------------
# Bug 3: ANY_CHAR granularity (fixes (.)\1 and char-boundary alignment)
# ---------------------------------------------------------------------------

class TestAnyCharGranularity:
    def test_any_char_is_single_code_unit(self):
        assert ANY_CHAR() == r"r'[\x00-\x7f]'"

    def test_dot_emits_newline_excluding_single_unit(self):
        # `.` (non-DOTALL) is one code unit that is NOT a line terminator, so the
        # emitted class excludes \n (0x0a) and \r (0x0d). It must NOT be the fully
        # permissive ANY_CHAR range (that let Fandango place a newline in a .-span,
        # producing non-matching strings -- 2026-07-07 scan, Bug B).
        fan = transpile(r".")
        assert DOT_CHAR() in fan
        assert r"r'[\x00-\x7f]'" not in fan
        assert "<utf8_char>" not in fan

    def test_semantic_dot_single_code_unit_no_newline(self):
        strings = fuzz_strings(r".", n=20)
        assert strings and all(len(s) == 1 for s in strings)
        # A newline must never be generated for `.` (would not match under no `s`).
        assert all(s not in ("\n", "\r") for s in strings), [repr(s) for s in strings]

    def test_backreference_constraint_still_emitted(self):
        fan = transpile(r"(.)\1")
        assert "latest_matched_group" in fan
        assert "has_preceeding_group" in fan

    def test_semantic_backref_matches(self):
        # (.)\1 must now actually produce matching strings (adjacent duplicates).
        strings = fuzz_strings(r"(.)\1", n=15)
        assert strings
        pat = re.compile(r"(.)\1")
        assert all(pat.search(s) for s in strings), [repr(s) for s in strings]


# ---------------------------------------------------------------------------
# Bug 3 in context: (.)\1 under the matchAll repetition rewrite (the headline
# case). Needs Stage 2 specialization + config; slower, so kept minimal.
# ---------------------------------------------------------------------------

def test_matchall_dot_backref_yields_multiple_matches():
    from pipeline.base_spec import build_base_spec, CAPTURE_GROUP_META
    from pipeline.specialize import specialize
    from pipeline.api_descriptors import DESCRIPTORS_BY_API
    from pipeline.config import load_config
    import fandango

    cfg = load_config()
    regex = r"(.)\1"
    base_fan, _, cg, _facts = build_base_spec(regex)
    base_with_meta = CAPTURE_GROUP_META + ",".join(cg) + "\n\n" + base_fan
    res = specialize(base_with_meta, regex, DESCRIPTORS_BY_API["matchAll"], cfg)

    inst = fandango.Fandango(res.fan_content, use_cache=False)
    strings = [str(x) for x in inst.fuzz(desired_solutions=10, max_generations=120, random_seed=0)]
    pat = re.compile(regex)
    with_two = [s for s in strings if len(pat.findall(s)) >= 2]
    assert with_two, f"no string had >=2 (.)\\1 matches: {[repr(s) for s in strings]}"


# ---------------------------------------------------------------------------
# Codegen: an empty alternation branch must emit `""`, not a bare `<r> ::= `.
# sre_parse factors common prefixes and leaves an EMPTY `[]` branch (the "end"
# arm of `(end|endblock)`; a trailing `|`; an empty group `()`). A bare RHS is a
# FandangoSyntaxError.
# ---------------------------------------------------------------------------

def _fandango_loads(regex: str) -> bool:
    import fandango
    fandango.Fandango(transpile(regex), use_cache=False)  # raises on bad grammar
    return True


class TestEmptyAlternationBranch:
    def test_no_bare_empty_rhs_emitted(self):
        fan = transpile(r"(end|endblock)")
        # Every rule line must have a non-empty RHS after `::=`.
        for line in fan.splitlines():
            if "::=" in line and not line.lstrip().startswith("#"):
                rhs = line.split("::=", 1)[1].split(":=", 1)[0]
                assert rhs.strip(), f"empty RHS emitted: {line!r}"

    def test_empty_branch_becomes_quoted_empty(self):
        fan = transpile(r"(end|endblock)")
        assert '::= ""' in fan  # the "end" arm is the explicit empty string

    @pytest.mark.parametrize("regex", [
        r"(end|endblock)",     # regex_283: prefix-factored empty branch
        r"(ms|s|y|)",           # trailing empty alternative
        r"a()b",                # empty group
        r"(?:x|)+",             # empty branch under a repeat
    ])
    def test_empty_alternative_grammar_loads(self, regex):
        assert _fandango_loads(regex)

    def test_semantic_both_alternatives_generated(self):
        # (end|endblock) must be able to produce BOTH "end" and "endblock".
        strings = set(fuzz_strings(r"^(end|endblock)$", n=20))
        pat = re.compile(r"^(end|endblock)$")
        assert all(pat.match(s) for s in strings), [repr(s) for s in strings]


# ---------------------------------------------------------------------------
# Codegen: raw control / high bytes must be escaped as \xHH, not emitted raw into
# terminals (NUL/newline/form-feed break the grammar text -> FandangoSyntaxError /
# "unterminated string literal"). The provenance comment must stay one ASCII line.
# ---------------------------------------------------------------------------

class TestRawByteEscaping:
    @pytest.mark.parametrize("regex", [
        r"[\f]",                         # regex_1426: lone form-feed literal
        r"[\x00-\x09\x0B\x0C\x1E\x1F]",  # regex_2644: control range
        r"[\x00-\x20\x7f-\xff]",         # regex_2048: NUL..0x20 + high bytes
        r"^([^\0])\0\0\0",               # regex_932: NUL literal + negated NUL class
    ])
    def test_control_byte_grammar_loads(self, regex):
        assert _fandango_loads(regex)

    def test_no_raw_control_byte_in_grammar(self):
        # Emitted grammar text must contain no raw C0 control / DEL byte.
        fan = transpile(r"[\x00-\x09\x0B\x0C\x1E\x1F]")
        raw = [hex(ord(ch)) for ch in fan if ord(ch) < 0x20 and ch not in "\n\t"]
        assert not raw, f"raw control bytes leaked into grammar: {raw}"

    def test_formfeed_emitted_as_hex_escape(self):
        fan = transpile(r"[\f]")
        assert r"\x0c" in fan and "\x0c" not in fan  # escaped text, not the raw byte

    def test_provenance_comment_single_line_for_raw_newline(self):
        # regex_1829: literal CR/LF in the pattern must not split the `# regex:` line.
        fan = transpile("\r\n|\r")
        header = fan.splitlines()[0]
        assert header.startswith("# regex:")
        assert "\r" not in header and r"\r" in header  # escaped, one line

    def test_provenance_comment_ascii_encodable(self):
        # The header must be writable as ASCII even for non-ASCII patterns.
        fan = transpile(r"caf\u{e9}")
        fan.splitlines()[0].encode("ascii")  # must not raise

    def test_semantic_control_class_membership(self):
        # Generated chars for a control-byte class must actually match the source.
        strings = fuzz_strings(r"[\x00-\x09\x0B\x0C\x1E\x1F]", n=8)
        assert strings
        pat = re.compile(normalize_js_regex(r"[\x00-\x09\x0B\x0C\x1E\x1F]"))
        assert all(pat.fullmatch(s) for s in strings), [repr(s) for s in strings]


# ---------------------------------------------------------------------------
# Front-end: a `-` next to a shorthand class inside [...] is a literal in JS
# ([\w-\.] = word chars, "-", "."), but sre_parse raises "bad character range".
# ---------------------------------------------------------------------------

from regex_fandango_transpiler import rewrite_js_class_shorthand_ranges


class TestClassShorthandHyphen:
    @pytest.mark.parametrize("src, exp", [
        (r"[\w-\.]", r"[\w\-\.]"),
        (r"[\s-\._]", r"[\s\-\._]"),
        (r"[\w-_]", r"[\w\-_]"),
        (r"[-\w]", r"[\-\w]"),     # `-` before a shorthand
        (r"[\w-]", r"[\w\-]"),      # `-` after a shorthand (trailing)
    ])
    def test_shorthand_adjacent_hyphen_escaped(self, src, exp):
        assert rewrite_js_class_shorthand_ranges(src) == exp

    @pytest.mark.parametrize("src", [r"[a-z]", r"[0-9a-f]", r"[\wa-z]", r"abc-def"])
    def test_genuine_ranges_and_outside_class_untouched(self, src):
        assert rewrite_js_class_shorthand_ranges(src) == src

    def test_escaped_backslash_before_shorthand(self):
        # [\\w-x] is an escaped backslash + literal w, then `-x` is a real range.
        assert rewrite_js_class_shorthand_ranges(r"[\\w-x]") == r"[\\w-x]"

    @pytest.mark.parametrize("regex", [
        r"([\w-\.]+)?",                              # regex_1562
        r"[\s-\._]",                                  # regex_1935
        r"^([\w.\-_]+)?\w+@[\w-_]+(\.\w+){1,2}$",     # regex_2682
    ])
    def test_previously_failing_now_transpile(self, regex):
        fan = transpile(regex)        # must not raise (bad character range)
        assert "<start> ::=" in fan

    def test_semantic_hyphen_is_member(self):
        # A generated string for [\w-\.]+ must match under the JS (literal-hyphen) read.
        strings = fuzz_strings(r"^[\w-\.]+$", n=12)
        assert strings
        pat = re.compile(normalize_js_regex(r"^[\w-\.]+$"))
        assert all(pat.fullmatch(s) for s in strings), [repr(s) for s in strings]


# ---------------------------------------------------------------------------
# Front-end: JS empty classes [] (nothing) and [^] (any char); Python rejects them.
# And UTF-16 surrogate escapes -> typed SurrogateEscapeUnmodeled (not a crash).
# ---------------------------------------------------------------------------

from regex_fandango_transpiler import (
    rewrite_js_empty_class, normalize_js_regex as _norm, SurrogateEscapeUnmodeled,
)


class TestEmptyClassAndSurrogates:
    def test_any_char_class(self):
        assert rewrite_js_empty_class(r"[^]*?x") == r"[\s\S]*?x"

    def test_empty_class_matches_nothing(self):
        assert rewrite_js_empty_class(r"[]abc") == r"[^\x00-\U0010FFFF]abc"

    @pytest.mark.parametrize("src", [r"[([]", r"[a]]", r"\[]", r"[^abc]"])
    def test_non_empty_classes_untouched(self, src):
        assert rewrite_js_empty_class(src) == src

    def test_leading_empty_class_then_literal(self):
        # `[]]` in JS is the empty class [] (nothing) then a literal `]`, NOT Python's
        # {]}. So it IS rewritten, matching the JS reading.
        assert rewrite_js_empty_class(r"[]]") == r"[^\x00-\U0010FFFF]]"

    def test_dotall_idiom_transpiles(self):
        # regex_2368: JisonLexerError:[^]*?Unrecognized text\.
        fan = transpile(r"JisonLexerError:[^]*?Unrecognized text\.")
        assert "<start> ::=" in fan

    def test_semantic_any_char_class_matches(self):
        strings = fuzz_strings(r"^a[^]b$", n=10)
        assert strings
        pat = re.compile(_norm(r"^a[^]b$"))
        assert all(pat.fullmatch(s) for s in strings), [repr(s) for s in strings]

    @pytest.mark.parametrize("pat", [r"\uD807", r"\U0000DEE0", "\ud807",
                                     r"(?:\uD807[\uDEE0-\uDEF8])"])
    def test_surrogate_escape_raises_typed(self, pat):
        with pytest.raises(SurrogateEscapeUnmodeled):
            _norm(pat)

    @pytest.mark.parametrize("pat", ["퟿", "", r"", "A"])
    def test_non_surrogate_not_rejected(self, pat):
        _norm(pat)  # must not raise
