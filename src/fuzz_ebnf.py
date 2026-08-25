from fandango import Fandango
import json 
import os 
from os import path 
import signal

from grammar_lib import estimate_unique_strings, num_constraints_in_grammar
from paths import (
    GENERATION_RECORD as RECORDS_FILE,
    GENERATED_TEST_INPUTS_DIR as TESTINPUTSPATH,
)

class TestsGeneratorAndFuzzer:
    def __init__(self):
        self.fandango_instance = None
        self.records = json.load(open(RECORDS_FILE, "r")) if path.exists(RECORDS_FILE) else []
        self.ebnf_file_path = ""
        self.regex = ""
        self.grammar = ""
        self.generated_inputs_records = [] # To store generated test inputs records
        if not os.path.exists(TESTINPUTSPATH):
            os.makedirs(TESTINPUTSPATH, exist_ok=True)

    def load_grammar(self, ebnf_file_path: str = "") -> None:
        with open(ebnf_file_path, "r") as f:
            ebnf_content = f.read()
        print("EBNF: ", ebnf_content)
        print("Fuzzing file: ", ebnf_file_path)
        try:
            self.fandango_instance = Fandango(ebnf_content, lazy = False, use_cache=False) #hangs on some grammars
            print("Initialized Fandango instance for fuzzing...")
        except Exception as e:
            self.fandango_instance = None
            print(f"Error initializing Fandango instance for file {ebnf_file_path}: {e}")
        
    def fuzz_grammar_no_constraints(self, num_samples: int = 10) -> list:
        def timeout_handler(signum, frame):
            raise TimeoutError("Fuzzing operation timed out after 2 minutes")

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(120)  # 2 minutes = 120 seconds
        
        # First, see how many unique strings we can get.
        unique_strings_estimate = estimate_unique_strings(self.fandango_instance)

        test_inputs = []
        try:
            if unique_strings_estimate < 100:
                print(f"Estimated unique strings is low ({unique_strings_estimate}), fuzzing with fewer samples.")
                try:
                    tree = self.fandango_instance.fuzz(desired_solutions=unique_strings_estimate, max_generations=num_samples)
                    for solution in tree:
                        test_inputs.append(str(solution))
                except Exception as e:
                    print(f"Error during fuzzing for regex {self.regex}: {e}")
            else:
                for round in range(num_samples//10):
                    if test_inputs == ['ERROR_TIMEOUT']:
                        test_inputs = []
                    try:    
                        tree = self.fandango_instance.fuzz(desired_solutions=num_samples//10, max_generations=num_samples)
                        for solution in tree:
                            test_inputs.append(str(solution))
                            
                        #new_inputs = [str(s) for s in self.fandango_instance.fuzz(desired_solutions=num_samples//10, max_generations=num_samples//10)]
                        #test_inputs.extend(new_inputs)
                        test_inputs = list(set(test_inputs))  # Remove duplicates
                        if tree == [] or len(tree) == 0 or len(tree) < num_samples//10:
                            print(f"No new inputs generated in round {round}, stopping early.")
                            break
                    except Exception as e:
                        print(f"Error during fuzzing round {round} for regex {self.regex}: {e}")
                        break
        except TimeoutError:
            print(f"Fuzzing timed out for regex: {self.regex}")
        finally:
            print(f"Generated {len(test_inputs)} test inputs for regex: {self.regex}")
            signal.alarm(0)  # Cancel the alarm

        return test_inputs

    def fuzz_grammar_with_constraints(self, num_samples: int = 10) -> list:

        def timeout_handler(signum, frame):
            raise TimeoutError("Fuzzing operation timed out after 2 minutes")

        signal.signal(signal.SIGALRM, timeout_handler)
        # signal.alarm(120)  # 2 minutes = 120 seconds
        signal.alarm(30)  # changing to 30s for a quicker turnaround
        
        test_inputs = []
        try:
            for round in range(num_samples//10):
                if test_inputs == ['ERROR_TIMEOUT']:
                    test_inputs = []
                try:    
                    tree = self.fandango_instance.fuzz(desired_solutions=num_samples//10, max_generations=num_samples)
                #new_inputs = []
                    for solution in tree:
                        #new_inputs.append(str(solution))
                        test_inputs.append(str(solution))
                        
                    #new_inputs = [str(s) for s in self.fandango_instance.fuzz(desired_solutions=num_samples//10, max_generations=num_samples//10)]
                    #test_inputs.extend(new_inputs)
                    test_inputs = list(set(test_inputs))  # Remove duplicates
                    if tree == [] or len(tree) == 0 or len(tree) < num_samples//10:
                        print(f"No new inputs generated in round {round}, stopping early.")
                        break
                except Exception as e:
                    print(f"Error during fuzzing round {round} for regex {self.regex}: {e}")
                    break
        except TimeoutError:
            print(f"Fuzzing timed out for regex: {self.regex}")
        finally:
            print(f"Generated {len(test_inputs)} test inputs for regex: {self.regex}")
            signal.alarm(0)  # Cancel the alarm

        return test_inputs

    def fuzz_grammar(self, num_samples: int = 10) -> list:
        test_inputs = ['ERROR_TIMEOUT']
        if self.fandango_instance is None:
            print(f"Fandango instance is None for file {self.ebnf_file_path}")
            return test_inputs
        
        # Are there any constraints in the grammar?
        num_constraints = num_constraints_in_grammar(self.fandango_instance)

        if num_constraints > 0:
            test_inputs = self.fuzz_grammar_with_constraints(num_samples=num_samples)    
        else:
            test_inputs = self.fuzz_grammar_no_constraints(num_samples=num_samples)

        self.fandango_instance = None  # Reset fandango instance
        return test_inputs
    
    # TODO: Optimize fuzzing by creating a JSON for each regex with its generated inputs to avoid JSON file bloat
    # and re-fuzzing already fuzzed grammars
    # Also, implement a way to skip already fuzzed grammars in the main fuzzing loop
    # This can be done by checking if the regex exists in the generated inputs records JSON file
    # and skipping if it does  
    # CREATE A DIR FOR JSON PER REGEX TO HOLD ITS GENERATED INPUTS
    def fuzz(self, num_inputs: int = 100, restart: int = 0) -> list:
        print("Starting fuzzing of generated grammars...")
        print(f"Total records to process: {len(self.records)}")
        total_records = len(self.records)
        current_record_index = restart
        for record in self.records[restart:]:
            print(f"Fuzzing grammars for regex: {record['regex']}")
            self.regex = record["regex"]
            record_results = {}
            record_results["regex"] = self.regex 
            record_results["inputs_ebnf"] = []
            path_to_grammars = record["output_dir"]
            if not path.exists(path_to_grammars):
                continue # Skip if the grammars output directory doesn't exist
            for grammar_mutation in os.listdir(record["output_dir"]):
                if grammar_mutation.endswith(".fan"):
                    self.ebnf_file_path = path.join(record["output_dir"], grammar_mutation)
                    self.load_grammar(self.ebnf_file_path)
                    test_inputs = self.fuzz_grammar(num_samples=num_inputs)
                    record_results["inputs_ebnf"].append({
                        "ebnf_file": self.ebnf_file_path,
                        "test_inputs": test_inputs
                    })
                    print(f"Fuzzed regex: {self.regex}, grammar: {grammar_mutation}, generated inputs: {len(test_inputs)}")
                    # Save test inputs for each grammar to a separate JSON file
                output_dir_name = record["output_dir"].split("/")[-1].split(".")[0]
                test_inputs_file = path.join(TESTINPUTSPATH, f"{output_dir_name}_inputs.json")
                with open(test_inputs_file, "w") as f:
                    json.dump(record_results, f, indent=2)
            
            current_record_index += 1
            print(f"Finished {current_record_index}/{total_records} records ({(current_record_index/total_records)*100:.2f}%).")
                
            #self.generated_inputs_records.append(record_results)
        # Save generated inputs records to a JSON file
        #with open("./generated_test_inputs.json", "w") as f:
        #    json.dump(self.generated_inputs_records, f, indent=2)
        #    print("Saved generated test inputs to ./generated_test_inputs.json")
        #return self.generated_inputs_records

__all__ = ['TestsGeneratorAndFuzzer']

'''
def __main__():
    generator_and_fuzzer = TestsGeneratorAndFuzzer()
    generator_and_fuzzer.fuzz()

if __name__ == "__main__":
    __main__()
'''    