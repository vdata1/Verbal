import unittest
import os
import subprocess
from fandango import Fandango


import importlib.util

def invoke_fandango_fuzz(fandango_file = "test.fan", sample_size=2, max_generations=2):
    "Invoke fandango fuzz command on a given grammar file"
    with open(fandango_file, "r") as f:
        grammar = f.read()
        fandango = Fandango(grammar)
        results = [str(s) for s in fandango.fuzz(desired_solutions=sample_size, warnings_are_errors=False, max_generations=max_generations)]
        return results
# Dynamically import the module to test
MODULE_PATH = '/Users/vdata/Desktop/CISPA_projects/verbal/regex_to_ebnf_test.py'
MODULE_NAME = 'regex_to_ebnf_test'

spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
regex_to_ebnf_test = importlib.util.module_from_spec(spec)
spec.loader.exec_module(regex_to_ebnf_test)

class TestRegexToEBNF(unittest.TestCase):
    def test_regex_to_ebnf_simple(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("a|b")
        results = invoke_fandango_fuzz("test.fan", sample_size=2, max_generations=2)

        for result in results:
            self.assertIn(result, ["a", "b"])
    def test_regex_to_ebnf_star(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("a*")
        results = invoke_fandango_fuzz("test.fan", sample_size=3, max_generations=2)
        for result in results:
            self.assertTrue(all(c == "a" for c in result) or result == "")

    def test_regex_to_ebnf_plus(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("a+")
        results = invoke_fandango_fuzz("test.fan", sample_size=3, max_generations=2)
        for result in results:
            self.assertTrue(len(result) >= 1 and all(c == "a" for c in result))

    def test_regex_to_ebnf_concat(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("ab")
        results = invoke_fandango_fuzz("test.fan", sample_size=2, max_generations=2)
        for result in results:
            self.assertEqual(result, "ab")

    def test_regex_to_ebnf_group(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("(a|b)c")
        results = invoke_fandango_fuzz("test.fan", sample_size=2, max_generations=2)
        self.assertIn("ac", results)
        self.assertIn("bc", results)

    def test_regex_to_ebnf_optional(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("a?")
        results = invoke_fandango_fuzz("test.fan", sample_size=2, max_generations=2)
        self.assertIn("", results)
        self.assertIn("a", results)

    def test_regex_to_ebnf_complex(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("(ab|cd)*e?")
        results = invoke_fandango_fuzz("test.fan", sample_size=5, max_generations=3)
        for result in results:
            self.assertTrue(result.endswith("e") or result.endswith(""))
            prefix = result[:-1] if result.endswith("e") else result
            self.assertTrue(all(prefix[i:i+2] in ["ab", "cd"] for i in range(0, len(prefix), 2)))

    def test_regex_to_ebnf_nested(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("((a|b)c)+d?")
        results = invoke_fandango_fuzz("test.fan", sample_size=5, max_generations=3)
        for result in results:
            self.assertTrue(result.endswith("d") or result.endswith(""))
            prefix = result[:-1] if result.endswith("d") else result
            self.assertTrue(len(prefix) >= 2)
            for i in range(0, len(prefix), 2):
                self.assertIn(prefix[i:i+2], ["ac", "bc"])

    def test_regex_to_ebnf_alternation_and_star(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("(a|b|c)*")
        results = invoke_fandango_fuzz("test.fan", sample_size=5, max_generations=3)
        for result in results:
            self.assertTrue(all(c in "abc" for c in result))
    def test_regex_to_ebnf_multiple_groups(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("(a|b)(c|d)")
        results = invoke_fandango_fuzz("test.fan", sample_size=4, max_generations=2)
        for result in results:
            self.assertIn(result, ["ac", "ad", "bc", "bd"])

    def test_regex_to_ebnf_nested_star(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("(ab*)*")  # shows a bug
        results = invoke_fandango_fuzz("test.fan", sample_size=5, max_generations=3)
        print("Results for (ab*)* :", results)
        for result in results:
            self.assertTrue(all(s.startswith("a") and set(s[1:]).issubset({"b"}) for s in [result[i:i+len("ab")] for i in range(0, len(result), len("ab"))] if s))
        
    def test_regex_to_ebnf_complex_concat(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("a(bc|de)+f?")
        results = invoke_fandango_fuzz("test.fan", sample_size=5, max_generations=3)
        for result in results:
            self.assertTrue(result.startswith("a"))
            self.assertTrue(result.endswith("f") or result.endswith("e") or result.endswith("c"))
            middle = result[1:-1] if result.endswith("f") else result[1:]
            self.assertTrue(all(middle[i:i+2] in ["bc", "de"] for i in range(0, len(middle), 2)))

    def test_regex_to_ebnf_long_alternation(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("a|b|c|d|e")
        results = invoke_fandango_fuzz("test.fan", sample_size=5, max_generations=2)
        for result in results:
            self.assertIn(result, ["a", "b", "c", "d", "e"])

    def test_regex_to_ebnf_optional_group(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("(ab)?c")
        results = invoke_fandango_fuzz("test.fan", sample_size=3, max_generations=2)
        self.assertIn("c", results)
        self.assertIn("abc", results)

    def test_regex_to_ebnf_multiple_optionals(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("a?b?c?")
        results = invoke_fandango_fuzz("test.fan", sample_size=8, max_generations=3)
        for result in results:
            self.assertTrue(set(result).issubset({"a", "b", "c"}))
            self.assertTrue(len(result) <= 3)

    def test_regex_to_ebnf_mixed_quantifiers(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("a+b?c*")
        results = invoke_fandango_fuzz("test.fan", sample_size=5, max_generations=3)
        for result in results:
            self.assertTrue(result.count("a") >= 1)
            self.assertTrue(result.count("b") <= 1)
            self.assertTrue(set(result.replace("a", "").replace("b", "")) <= {"c"})

    def test_regex_to_ebnf_complex_nested(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("((a|b)*c)+d?")
        results = invoke_fandango_fuzz("test.fan", sample_size=5, max_generations=3)
        for result in results:
            self.assertTrue(result.endswith("d") or result.endswith("c"))
            prefix = result[:-1] if result.endswith("d") else result
            self.assertTrue("c" in prefix)

    def test_regex_to_ebnf_long_concat(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("abcde")
        results = invoke_fandango_fuzz("test.fan", sample_size=1, max_generations=2)
        for result in results:
            self.assertEqual(result, "abcde")

    def test_regex_to_ebnf_alternation_with_star_and_optional(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("(a|b)*c?")
        results = invoke_fandango_fuzz("test.fan", sample_size=5, max_generations=3)
        for result in results:
            self.assertTrue(all(c in "ab" for c in result.replace("c", "")))
            self.assertTrue(result.endswith("c") or result == "" or all(c in "ab" for c in result))
    def test_regex_to_ebnf_special_case(self):
        regex_to_ebnf_test.generate_ebnf_from_regex("^|^wEF^|^ufUu+^I")
        results = invoke_fandango_fuzz("test.fan", sample_size=5, max_generations=3)
        expected = ["", "wEF", "ufUuI", "ufUuuI", "ufUuuuI"]
        for result in results:
            self.assertTrue(
                result == "" or
                result == "wEF" or
                (result.startswith("ufUu") and result.endswith("I") and len(result) >= 6)
            )
if __name__ == '__main__':
    unittest.main()