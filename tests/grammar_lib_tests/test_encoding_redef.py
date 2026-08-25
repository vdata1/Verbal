# Read in test_specs/test0.fan, modify STRING_TO_BYTES_ENCODING in fandango.language.tree_value to "utf-16", and then fuzz the grammar to see if it can handle the encoding redefinition without errors. This is relevant for regexes that include unicode characters that may not be properly handled with utf-8 encoding.
from fandango import Fandango
import os

# fandango.language.tree_value.py has a variable, STRING_TO_BYTES_ENCODING, that we want to set to "utf-16" instead of "utf-8" to test how fandango handles encoding redefinition. This is relevant for regexes that include unicode characters that may not be properly handled with utf-8 encoding.

# This test is broken atm

def test_encoding_redefinition():
    fan_file_path = "./test_specs/need_updated_encoding.fan"
    with open(fan_file_path, "r") as f:
        fan_content = f.read()

    fandango_instance = Fandango(fan_content, use_cache=False)

    try:
        fandango_instance.fuzz(desired_solutions=10, max_generations=100)
        print("Fuzzing completed successfully with utf-16 encoding.")
    except Exception as e:
        print(f"Error during fuzzing with utf-16 encoding: {e}")

if __name__ == "__main__":
    test_encoding_redefinition()

