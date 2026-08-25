import unittest
from regex_to_ebnf import regex_to_ebnf, generate_ebnf_from_regex

class TestRegexToEBNF(unittest.TestCase):
    def test_literal(self):
        ebnf = regex_to_ebnf("a")
        self.assertIn("'a'", ebnf)

    def test_concat(self):
        ebnf = regex_to_ebnf("ab")
        self.assertIn("'a'", ebnf)
        self.assertIn("'b'", ebnf)

    def test_alternation(self):
        ebnf = regex_to_ebnf("a|b")
        self.assertIn("'a'", ebnf)
        self.assertIn("'b'", ebnf)
        self.assertIn("|", ebnf)

    def test_kleene_star(self):
        ebnf = regex_to_ebnf("a*")
        self.assertIn("'a'", ebnf)

    def test_plus(self):
        ebnf = regex_to_ebnf("a+")
        self.assertIn("'a'", ebnf)

    def test_optional(self):
        ebnf = regex_to_ebnf("a?")
        self.assertIn("'a'", ebnf)

    def test_group(self):
        ebnf = regex_to_ebnf("(ab)")
        self.assertIn("'a'", ebnf)
        self.assertIn("'b'", ebnf)

    def test_nested_group(self):
        ebnf = regex_to_ebnf("a(b|c)d")
        self.assertIn("'a'", ebnf)
        self.assertIn("'b'", ebnf)
        self.assertIn("'c'", ebnf)
        self.assertIn("'d'", ebnf)

    def test_character_class(self):
        ebnf = regex_to_ebnf("[abc]")
        self.assertIn("'a'", ebnf)
        self.assertIn("'b'", ebnf)
        self.assertIn("'c'", ebnf)

    def test_character_range(self):
        ebnf = regex_to_ebnf("[a-c]")
        self.assertIn("'a'", ebnf)
        self.assertIn("'b'", ebnf)
        self.assertIn("'c'", ebnf)

    def test_any(self):
        ebnf = regex_to_ebnf(".")
        self.assertIn("SPECIALS", ebnf)  # . should match specials

    def test_repeat_exact(self):
        ebnf = regex_to_ebnf("a{3}")
        self.assertIn("'a'", ebnf)

    def test_repeat_range(self):
        ebnf = regex_to_ebnf("a{2,4}")
        self.assertIn("'a'", ebnf)

    def test_digit_class(self):
        ebnf = regex_to_ebnf(r"\d")
        self.assertIn("DIGITS", ebnf)

    def test_word_class(self):
        ebnf = regex_to_ebnf(r"\w")
        self.assertIn("LETTERS", ebnf)
        self.assertIn("DIGITS", ebnf)

    def test_not_digit_class(self):
        ebnf = regex_to_ebnf(r"\D")
        self.assertIn("SPECIALS", ebnf)

    def test_not_word_class(self):
        ebnf = regex_to_ebnf(r"\W")
        self.assertIn("SPECIALS", ebnf)

    def test_space_class(self):
        ebnf = regex_to_ebnf(r"\s")
        self.assertIn("SPECIALS", ebnf)

    def test_not_space_class(self):
        ebnf = regex_to_ebnf(r"\S")
        self.assertIn("LETTERS", ebnf)

    def test_anchor_start(self):
        ebnf = regex_to_ebnf(r"^abc")
        self.assertIn("'a'", ebnf)

    def test_anchor_end(self):
        ebnf = regex_to_ebnf(r"abc$")
        self.assertIn("'c'", ebnf)

    def test_escape(self):
        ebnf = regex_to_ebnf(r"\.")
        self.assertIn("'.'", ebnf)

    def test_complex(self):
        ebnf = regex_to_ebnf(r"(a|b)*c\d+")
        self.assertIn("'a'", ebnf)
        self.assertIn("'b'", ebnf)
        self.assertIn("'c'", ebnf)
        self.assertIn("DIGITS", ebnf)

    def test_generate_ebnf_from_regex(self):
        ebnf = generate_ebnf_from_regex("a(b|c)*d?")
        self.assertIn("<start>", ebnf)
        self.assertIn("'a'", ebnf)
        self.assertIn("'b'", ebnf)
        self.assertIn("'c'", ebnf)
        self.assertIn("'d'", ebnf)

if __name__ == "__main__":
    unittest.main()

