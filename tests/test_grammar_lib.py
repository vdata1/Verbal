from grammar_lib import estimate_unique_strings

def test_grammar_lib_with_a_fan_spec():
    from fandango import Fandango
    fan_file_path = "./grammar_lib_tests/test_specs/test1.fan"
    with open(fan_file_path, "r") as f:
        fan_content = f.read()
    fandango_instance = Fandango(fan_content, use_cache=False)

    fandango_instance.fuzz()

    estimate = estimate_unique_strings(fandango_instance)
    print(f"Estimated unique strings for test.fan: {estimate}")

if __name__ == "__main__":
    test_grammar_lib_with_a_fan_spec()