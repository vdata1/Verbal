from fandango import Fandango
import subprocess
import json
import importlib

# Dynamically import the module to test
MODULE_PATH = '/Users/vdata/Desktop/CISPA_projects/verbal/regex_to_ebnf_test.py'
MODULE_NAME = 'regex_to_ebnf_test'

spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
regex_to_ebnf_test = importlib.util.module_from_spec(spec)
spec.loader.exec_module(regex_to_ebnf_test)


def prepare_test_code_runtime(runtime, regex, input_test):
    test_script = ""
    if runtime == "node" or runtime == "deno":
        test_script = f"""
        const Regex = new RegExp("{regex}");
        const result = Regex.test("{input_test}");
        console.log(result);
        """
    return test_script

def run_code_on_runtime(runtime, test_script):
    res = {}
    if runtime == "deno":
        res = subprocess.run(
            ["deno", "eval", test_script],
            capture_output=True,
            text=True
        )
    elif runtime == "node":
        res = subprocess.run(
            [runtime, "-e", test_script],
            capture_output=True,
            text=True
        )
        print("Node Result: ", res.stdout)
    return res



def invoke_fandango_fuzz(file, sample_size=10, max_generations=10):
    "Invoke fandango fuzz command on a given grammar file"
    with open(file, "r") as f:
        grammar = f.read()
        fandango = Fandango(grammar)
        return fandango.fuzz(desired_solutions=sample_size, warnings_are_errors=False, max_generations=max_generations)
def main():
    regex = "(ab*)*"
    generate_ebnf_from_regex = regex_to_ebnf_test.generate_ebnf_from_regex
    ebnf_grammar = generate_ebnf_from_regex(regex)
    #print("EBNF Grammar:", ebnf_grammar)
    fandango_file = "test.fan"
    max_generations = 10
    results = [str(s) for s in invoke_fandango_fuzz(fandango_file, sample_size=max_generations, max_generations=max_generations)]
    #print("Results: ", results)  # Print the generated samples
    for result in results:
        test_code = prepare_test_code_runtime("node", regex, result)
        print("Test Code: ", test_code)
        result = run_code_on_runtime("node", test_code)
        print("Test Result: ", result.stdout)
if __name__ == "__main__":
    main()


