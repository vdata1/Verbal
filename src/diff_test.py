import random
import subprocess 
import json 
import os
import os.path as path
from runtime_tester import runtime_tester
from paths import (
    GENERATED_UNIT_TESTS_DIR as GENERATEDUNITTESTSPATH,
    DIFF_TEST_RESULTS_DIR as RESULTSDIR,
)

RESULTSFILENAME = "diff_test_results.json"

class DiffTester(runtime_tester): 
    def __init__(self, generated_unit_tests_path: str = GENERATEDUNITTESTSPATH, results_filename: str = RESULTSFILENAME): 
        """
        STRUCTURE: 
        self.unit_tests_results= {
            "unitTestName":{
                   "Node": {
                    "stdout": "output", 
                    "stderr": "output"
                   }, 
                   "Deno": {
                    "stdout": "output", 
                    "stderr": "output"
                   }, 
                   "Bun": {
                    "stdout": "output", 
                    "stderr": "output"
                   }, 
            }, 
        .....
        }
        """

        super().__init__()
        self.unit_tests_results = {} 
        self.generated_unit_tests_path = generated_unit_tests_path
        self.results_filename = results_filename
        self.tests_results = {} 
        if not os.path.exists(RESULTSDIR):
            os.makedirs(RESULTSDIR, exist_ok=True)
    
    def diff_test(self, runtimes: list = ["node", "deno", "bun"], numOfTestsPerRegex=-1) -> None:
        self.tests_list = self.collect_tests(numOfTests=numOfTestsPerRegex)
        
        total_tests = len(self.tests_list)
        i = 0
        last_regex = ""
        this_regex = ""
        for testfile_path in self.tests_list:
            # Which regex are we testing?
            this_regex = testfile_path.split("/")[-3] # Because the structure is generated_unit_tests/regex_114/mutated_grammar_0/generated_unit_tests_0.js 
            if this_regex != last_regex:
                print(f"Now testing regex: {this_regex} (test file: {testfile_path})")
                # If it's not the first time we change...
                if last_regex != "":
                    # Save intermediate results to a JSON file after finishing all tests for a regex, so we don't lose all progress if the process is interrupted, and also to monitor progress in real time without waiting for the entire process to finish.
                    self.write_json_results(last_regex)
                    # Reset tests results for the next regex
                    self.tests_results = {}
                last_regex = this_regex
            for runtime in runtimes:
                print(f"Running test file: {testfile_path} on runtime: {runtime}")
                self.tests_results[testfile_path] = self.tests_results.get(testfile_path, {})
                self.tests_results[testfile_path][runtime] = self.run_test(runtime, testfile_path)
            i += 1
            
            print("Progress: ", i, "/", total_tests, "({:.2f}%)".format(i/total_tests*100))

        # After finishing all tests, save the final results to a JSON file
        self.write_json_results(this_regex)

    def write_json_results(self, regex_name: str = None) -> None: 
        # if file exists, just delete it and make a new one lol
        if regex_name:
            results_filename = f"diff_test_results_{regex_name}.json"
        else:
            results_filename = self.results_filename

        # Make the path
        results_file_path = path.join(RESULTSDIR, results_filename)

        if path.exists(results_file_path):
            os.remove(results_file_path)
        
        with open(results_file_path, "w") as f:
            json.dump(self.tests_results, f, indent=4)