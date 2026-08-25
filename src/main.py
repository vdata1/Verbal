import os
from generator_mutator import regex_to_grammar_generator 
from fuzz_ebnf import TestsGeneratorAndFuzzer
from tests_generator import UnitTestGenerator
from runtime_tester import runtime_tester 
from diff_test import DiffTester 
import subprocess
import argparse
import sys
import json

from paths import (
    REGEX_CORPUS as REGEXFILEPATH,
    GENERATED_GRAMMARS_DIR as grammars_output_dir,
    GENERATED_TEST_INPUTS_DIR as inputs_records_dir,
    GENERATED_UNIT_TESTS_DIR as GENERATEDUNITTESTSPATH,
    ensure_results_dirs,
)

num_grammars_to_generate_per_regex = 5
inputs_records = []

def load_test_inputs(file_path: str) -> list:
    with open(file_path, "r") as f:
        inputs_records = json.load(f)
    return inputs_records

def run_generator(REGEXFILEPATH: str = REGEXFILEPATH, num_grammars_to_generate_per_regex: int = num_grammars_to_generate_per_regex, constraints_only: bool = False, top_k: int = -1) -> None:
    generator = regex_to_grammar_generator(regex="", FilePath=REGEXFILEPATH, num_grammars=num_grammars_to_generate_per_regex, constraints_only=constraints_only)
    generator.start(num_mutations=num_grammars_to_generate_per_regex, top_k=top_k)

def fuzz(num_inputs: int = 100, restart: int = 0) -> None:
    #TESTINPUTSPATH = "./generated_test_inputs"
    #if not os.path.exists(TESTINPUTSPATH):
    #        os.makedirs(TESTINPUTSPATH, exist_ok=True)
    generator_and_fuzzer = TestsGeneratorAndFuzzer()
    generator_and_fuzzer.fuzz(num_inputs=num_inputs, restart=restart)

def generate_tests(num_tests: int = -1) -> None:
    print("Processing unit test generator...")
    index = 0
    total_records = len(os.listdir(inputs_records_dir))
    for test_input_record in os.listdir(inputs_records_dir):
            inputs_records_path = os.path.join(inputs_records_dir, test_input_record)
            #inputs_records = load_test_inputs(inputs_records_path)
            test_generator = UnitTestGenerator()
            test_generator.generate_unit_tests(inputs_records_path=inputs_records_path, num_tests=num_tests)
            index += 1
            print(f"Processed {index}/{total_records} ({(index/total_records)*100:.2f}%)")
    print("Unit test generator, Done.")

def __main__():
    
    parser = argparse.ArgumentParser(description='Regex grammar generation and fuzzing tool')
    parser.add_argument('-g', '--generate-grammars', action='store_true', help='Generate grammars only')
    parser.add_argument('-c', '--constraints-only', action='store_true', help='Generate only grammars that have constraints, i.e., that have some special features')
    parser.add_argument('-f', '--fuzz-grammars', action='store_true', help='Fuzz generated grammars')
    parser.add_argument('-fn', '--fuzz-num-inputs', type=int, default=100, help='Number of inputs to generate per grammar (default: 100)')
    parser.add_argument('-fr', '--fuzz-restart', type=int, default=0, help='If fuzzing is interrupted, use this flag with the number of records already processed to restart from where it left off (default: 0)')
    parser.add_argument('-d', '--differential-testing', action='store_true', help='Apply differential testing')
    parser.add_argument('-t', '--test-runtime', type=str, help='Test one specific runtime by name')
    parser.add_argument('-n', '--num-grammars', type=int, default=num_grammars_to_generate_per_regex, help='Number of grammars to generate per regex (default: 5)')
    parser.add_argument('-r', '--regex-file', type=str, default=REGEXFILEPATH, help='Path to regex file (default: ../uniq-regexes-8.json)')
    parser.add_argument('-u', '--generate-tests', action='store_true', help='Generate unit tests from fuzzed inputs')
    parser.add_argument('-un', '--num-tests', type=int, default=-1, help='Number of tests to generate per grammar (default: all)')
    parser.add_argument('-k', '--top-k', type=int, default=-1, help='If passed, only do the first k. Useful for testing the pipeline on a smaller number of regexes.')
    parser.add_argument('-dn', '--diff-test-num-tests', type=int, default=-1, help='Number of tests to run per regex in the differential testing phase (default: all). This is useful for debugging and for running the differential testing phase faster on a smaller number of tests.')

    # Main way to run: python main.py -g -f -u -d ... -r ../uniq-regexes-sample.json
    # For only constraints no mutations: python main.py -g -c -n 0 -f -u -d 
    # For debugging the grammar generator: python main.py -g -n=0 -c -k=20 (top 20)
    # Run the whole thing for a subset of the constrain regex: python main.py -g -c -n 0 -f -u -un 50 -d -k 1000

    # python main.py -u -un 50 -- Generate 50 unit tests per grammar, for all grammars in the generated_test_inputs directory. This is useful for testing the unit test generator independently.

    args = parser.parse_args()

    if not any(vars(args).values()):
        parser.print_help()
        sys.exit(1)

    # Make sure the results/ output tree exists regardless of CWD.
    ensure_results_dirs()

    # Generating grammars is pretty reliable and quick.
    if args.generate_grammars:
        # Check if fuzz-restart is not zero, in which case we can skip generation
        if args.fuzz_restart != 0:
            print(f"Skipping grammar generation because fuzz-restart is set to {args.fuzz_restart}. If you want to regenerate grammars, please set fuzz-restart to 0.")
        else:
            print("Generating grammars...")
            run_generator(REGEXFILEPATH=args.regex_file, num_grammars_to_generate_per_regex=args.num_grammars, constraints_only=args.constraints_only, top_k=args.top_k)

    # Fuzzing grammars can be a little slower, but intermediate results are already written out each time.
    if args.fuzz_grammars:
        print("Fuzzing grammars...")
        if os.path.exists(grammars_output_dir):
            fuzz(num_inputs=args.fuzz_num_inputs, restart=args.fuzz_restart)
        else:
            print(f"Error: Grammars output directory '{grammars_output_dir}' does not exist. Please generate grammars first.")
            exit(1)

    # Generating unit tests from fuzzed inputs (and regex pairs) also pretty fast.
    if args.generate_tests:
        generate_tests(num_tests=args.num_tests)

    # Running the differential test is the final step, and this can also be slow
    # but we save results after each regex to avoid losing progress and to monitor results in real time.
    if args.differential_testing:
        print("Running differential testing...")
        diff_tester = DiffTester(generated_unit_tests_path=GENERATEDUNITTESTSPATH)
        diff_tester.diff_test(numOfTestsPerRegex=args.diff_test_num_tests)
        

    if args.test_runtime:
        print(f"Testing runtime: {args.test_runtime}")
        tester = runtime_tester(generated_unit_tests_path=GENERATEDUNITTESTSPATH)
        tester.test_runtime(args.test_runtime)

if __name__ == "__main__":
    __main__()