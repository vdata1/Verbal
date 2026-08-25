
from string import Template 
import random
import json 
import os
import os.path as path

from paths import (
    GENERATED_UNIT_TESTS_DIR as UNITTESTSPATH,
    GENERATED_TEST_INPUTS_DIR,
    UNIT_TEST_TEMPLATES_DIR,
)

# Legacy default for load_test_inputs(); in practice main.py always passes an
# explicit per-regex inputs record path.
TESTINPUTPATH = os.path.join(GENERATED_TEST_INPUTS_DIR, "generated_test_inputs.json")

CATCH_TEMPLATE = """ catch (error) {
    console.log(error)
    // Go through the possible errors that could have occured, with a unique
    // ret code for each.
    if (error instanceof SyntaxError) {
        process.exit(11);
    }
    // Any other case, exit with -1
    process.exit(-1);
}
"""

EXTRA_DEFS = """function str_to_bytes(str) {
    const encoder = new TextEncoder();
    const byte_array = encoder.encode(str);
    // Return a string representation of the byte array, where each byte is represented as \\xNN
    return Array.from(byte_array).map(byte => '\\\\x' + byte.toString(16).padStart(2, '0')).join('');
}
"""

if not os.path.exists(UNITTESTSPATH):
    os.mkdir(UNITTESTSPATH)

'''
Structure of generated_test_inputs: 
[
{
    "regex1": ".+trying to set field missing which is not declared in the model.",
        "inputs_ebnf": [
        {
            "ebnf_file": "./generated_grammars/regex_38/mutated_grammar_3.fan",
            "test_inputs": [str, str, str ....] 
        }{
            "ebnf_file": "path2...",
            "test_inputs": [str, str, str ....] 
        }
        ]
},
{
    "regex": "regex2", 
        "inputs_ebnf": [
        {
            "ebnf_file": "regex2path1",
            "test_inputs": [str, str, str ....] 
        }{
            "ebnf_file": "regex2path2...",
            "test_inputs": [str, str, str ....] 
        }
        ]
}.....
]
'''



template_dir = UNIT_TEST_TEMPLATES_DIR
class UnitTestGenerator:
    def __init__(self, template_dir = template_dir):
        self.template_dir = template_dir
        self.templates = self.load_templates()
        self.test_obj = {} # To hold test object data: regex, input, exec_time, expected outputs 
        self.unit_test_cases = [] # To hold generated unit test cases: [{regex, input, test_per_regex_flag:{"\g", "\m", ...}}, ...]}, ...]
        self.test_input_path = TESTINPUTPATH
        self.test_inputs = {}
        self.regex_flags = ["g", "m", "i", "s", "u", "y", "v"] # JS regex flags, v flag is new to the runtimes
        self.tests = [] 
        self.regex_counter = 0 
        self.file_counter = 0

    def load_templates(self) -> dict:
        templates = {}
        for filename in os.listdir(self.template_dir):
            if filename.endswith(".template"):
                template_name = filename[:-9]  # Remove .template extension
                with open(path.join(self.template_dir, filename), "r") as f:
                    templates[template_name] = Template(f.read())
        return templates
    
    def load_test_inputs(self, test_inputs_path=TESTINPUTPATH):
        self.test_input_path = test_inputs_path
        with open(self.test_input_path, "r") as f: 
            self.test_inputs = json.load(f)
        return self.test_inputs
    
    def prepare_test_obj(self, regex_record: dict, ebnf_record: dict):
        self.test_obj = {}
        self.test_obj["regex"] = regex_record["regex"]
        self.test_obj["ebnf_file"] = ebnf_record["ebnf_file"]
        self.test_obj["test_inputs"] = ebnf_record["test_inputs"]
        return self.test_obj
        
    '''
    {'regex': '(#Electron-builder output|\\/dist_electron)', 'inputs_ebnf': [{'ebnf_file': './generated_grammars/regex_970/mutated_grammar_0.fan', 'test_inputs': ['/dist_electron', '#Electron-builder output']}, {'ebnf_file': './generated_grammars/regex_970/mutated_grammar_1.fan', 'test_inputs': ['#Electron-builder output/dist_electron']}]}

    '''
    def sanitize_test_input(self, test_input: str) -> str:
        # Escape backslashes and double quotes in the test input for safe inclusion in JavaScript string literals
        sanitized_input = test_input.replace("\\", "\\\\").replace("\"", "\\\"").replace('\'', "\\\'")
        # Convert newlines to their escaped representation so that the string is ok
        sanitized_input = sanitized_input.replace("\n", "\\n").replace("\r", "\\r")
        return sanitized_input
    
    def generate_unit_tests(self, inputs_records_path: str = TESTINPUTPATH, num_tests: int = -1) -> list:
        # Load the test inputs from the record
        self.load_test_inputs(inputs_records_path)
        # Get the regex name from the inputs_record_path, it'll be the last part.
        # <path>/regex_970_inputs.json -> regex_970
        regex_name = path.basename(inputs_records_path).split("_inputs.json")[0]
        print(f"Generating unit tests for regex: {regex_name}")
        templates_list = list(self.templates.items())

        for ebnf_record in self.test_inputs["inputs_ebnf"]:

            # Limit is per grammar.
            num_tests_generated = 0

            # Sometimes, there are mutated grammars; this for loop is for that.
            # Each mutated grammar should have it's own subdirectory to write unit tests into.
            test_output_dir = path.join(UNITTESTSPATH, regex_name, f"mutated_grammar_{self.regex_counter}")
            self.prepare_test_obj(self.test_inputs, ebnf_record)
            test_inputs_sample = self.test_obj["test_inputs"]

            for test_input in test_inputs_sample:

                if num_tests != -1 and num_tests_generated >= num_tests:
                    print(f"Generated {num_tests_generated} tests. Stopping generation.")
                    break 

                test_cases = []

                # Write a unit test for each template, for each regex flag.
                for template_name, template in templates_list:
                    for flag in self.regex_flags:
                        try:
                            test_case = template.substitute(
                                regex=self.sanitize_regex_for_string_literal(self.test_obj["regex"]),
                                regex_backtick=self.sanitize_regex_for_backtick(self.test_obj["regex"]),
                                regex_slash=self.sanitize_regex_for_slash(self.test_obj["regex"]),
                                input=self.sanitize_test_input(test_input),
                                flag=flag,
                                regex2=self.sanitize_regex_for_string_literal(self.test_obj["regex"]),
                                regex2_slash=self.sanitize_regex_for_slash(self.test_obj["regex"]),
                                input2=self.sanitize_test_input(random.choice(test_inputs_sample)),
                                flag2=random.choice(self.regex_flags),
                                catch=CATCH_TEMPLATE,
                                extra_defs=EXTRA_DEFS,
                                convert_start="str_to_bytes(",  # Convert the string into bytes so as to avoid display issues
                                convert_end=")"                 # and minute differences you get capturing stdout.
                            )
                            test_cases.append(test_case)
                            num_tests_generated += 1
                            if num_tests != -1 and num_tests_generated >= num_tests:
                                # print(f"Generated {num_tests_generated} tests for this grammar, reached the limit of num_tests={num_tests}. Stopping generation for this grammar.")
                                break # And then do next grammar
                        except Exception as e:
                            print(f"Error instantiating template {template_name}: {e}")
                            continue

                self.unit_test_cases.append({
                    "regex": self.test_obj["regex"],
                    "ebnf_file": self.test_obj["ebnf_file"],
                    "test_input": test_input,
                    "test_cases": test_cases
                })

                # Add the regex_name at the end of the output dir to distinguish between different regexes' unit tests
                self.write_test_cases_to_file(output_dir=test_output_dir)

                if num_tests != -1 and num_tests_generated >= num_tests:
                    # print(f"Generated {num_tests_generated} tests for this grammar, reached the limit of num_tests={num_tests}. Stopping generation for this grammar.")
                    break # And then do next grammar

                self.unit_test_cases = [] # Reset for next input

            # Moving on to a new mutated grammar; 
            # Increment regex counter to create a new subdirectory for the next mutated grammar's unit tests, 
            # and reset file counter to 0 for the new subdirectory
            self.regex_counter += 1
            self.file_counter = 0 

        #return self.unit_test_cases
    
    def sanitize_regex_for_string_literal(self, regex: str) -> str:
        # Escape double quotes in the regex for safe inclusion in JavaScript string literals
        # Just add an extra backslash before each backslash to make sure it's preserved in the final test case, and also escape double quotes and single quotes.
        sanitized_regex = regex.replace("\\", "\\\\").replace("\"", "\\\"").replace('\'', "\\\'")
        return sanitized_regex

    def sanitize_regex_for_backtick(self, regex: str) -> str:
        # Escape backticks in the regex for safe inclusion in JavaScript template literals
        sanitized_regex = regex.replace("`", "\\`")
        return sanitized_regex

    def sanitize_regex_for_slash(self, regex: str) -> str:
        # Escape forward slashes in the regex for safe inclusion in JavaScript regex literals
        # sanitized_regex = regex.replace("/", "\\/") # <- super confused about this
        sanitized_regex = regex # For some reason we might not need this anymore?
        return sanitized_regex

    def sanitize_for_javascript_comment(self, text: str) -> str:
        # Escape */ to prevent ending the comment early
        sanitized_text = text.replace("*/", "*\\/").replace("/*", "/\\*")
        # Also convert newlines to their escaped representation so that the comment is ok
        sanitized_text = sanitized_text.replace("\n", "\\n").replace("\r", "\\r")
        return sanitized_text

    def write_test_cases_to_file(self, output_dir: str = UNITTESTSPATH):
        
        # Just make sure the output dir exists; if not, create it.
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # For each test case we generated...
        for test in self.unit_test_cases:
            # For each test...
            for testCase in test["test_cases"]:
                # The output file name will be like: generated_grammars/regex_970/mutated_grammar_0/generated_unit_tests_{i}.js
                output_file = path.join(output_dir, f"generated_unit_tests_{self.file_counter}.js")
                # Add try/catch for error handling in the generated test case
                try:
                    # Open with errors="surrogatepass" to allow writing of any unicode characters, even if they can't be encoded in utf-8 (like lone surrogates), which we've seen in some test inputs.
                    with open(output_file, "w", encoding="utf-8", errors="surrogatepass") as f:
                        # Saved here in case we want to do some preprocessing
                        test_content = testCase
                        generated_test = f"// Regex: {self.sanitize_for_javascript_comment(str(test['regex']))}\n// Input: {self.sanitize_for_javascript_comment(str(test['test_input']))}\n{test_content}"
                        f.write(generated_test)
                        # File counter keeps track of how many test files we've written.
                        # This gets reset by generate_unit_tests when moving on to a new grammar.
                        self.file_counter += 1
                except Exception as e:
                    # Some errors we've seen:
                    # - UnicodeEncodeError: 'utf-8' codec can't encode character '\u____' in position 0: surrogates not allowed
                    #                       (sometimes the <byte>* will result in inputs with surrogates)
                    # ! Note:               with errors="surrogatepass" in open() should prevent this error by allowing surrogates to be written, 
                    #                       but if it still happens, we catch it here and log it.
                    print(f"Error writing test case to {output_file}: {e}")
            print(f"Written {len(self.unit_test_cases)} unit test cases to {output_file}")

__all__ = ["UnitTestGenerator"]

'''
def main():
    unit_test_generator = UnitTestGenerator()
    unit_tests = unit_test_generator.generate_unit_tests()
    for idx, test in enumerate(unit_tests):
        print(f"--- Unit Test Case {idx+1} ---")
        print(test)
        print("\n")
if __name__ == "__main__":
    main()
'''