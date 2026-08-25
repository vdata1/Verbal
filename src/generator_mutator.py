from regex_fandango_transpiler import RegexToFandangoTranslator
from grammar_mutator import Mutator
import os
import os.path as path
import json

from paths import (
    REGEX_CORPUS as REGEXFILEPATH,
    GENERATED_GRAMMARS_DIR as grammars_output_dir,
    GENERATION_RECORD,
)

num_grammars_to_generate_per_regex = 5

# Create output dir
os.makedirs(grammars_output_dir, exist_ok=True)

class regex_to_grammar_generator:
    def __init__(self, regex: str, FilePath: str = REGEXFILEPATH, num_grammars: int = num_grammars_to_generate_per_regex, constraints_only: bool = False):
        self.regex = regex
        self.transpiler = RegexToFandangoTranslator()
        self.mutator = Mutator()
        self.FilePath = FilePath
        self.num_grammars = num_grammars
        self.constraints_only = constraints_only
        self.regex_count = 0 # To use for dir name for each regex and to keep track of number of regexes processed
        self.mutation_count = 0 # To use for naming mutated grammar files
        self.current_output_dir = ""
        self.grammar = ""
        self.record = []

    def cleanup(self):
        self.transpiler = RegexToFandangoTranslator()
        self.mutator = Mutator()
        #self.regex_count = 0
        self.mutation_count = 0
        #self.current_output_dir = ""
        self.grammar = ""

    def create_output_dir_for_regex(self) -> str:
        dir_name = f"regex_{self.regex_count}"
        output_dir = path.join(grammars_output_dir, dir_name)
        os.makedirs(output_dir, exist_ok=True)
        self.regex_count += 1
        return output_dir

    def write_fan_files(self, grammars: str) -> None:
        self.record.append({"regex": self.regex, "num_grammars": len(grammars), "output_dir": self.current_output_dir})
        for grammar in grammars:
            filename = f"mutated_grammar_{self.mutation_count}.fan"
            file_path = path.join(self.current_output_dir, filename)   
            with open(file_path, "w") as f:
                f.write(grammar)
            self.mutation_count += 1
            print(f"Written mutated grammar to {file_path}")
    

    def generate_grammar(self, regex: str) -> tuple[str, int]:

        return self.transpiler.generate_ebnf_grammar_with_constraints(regex)

    def generate_mutated_grammars(self, num_mutations: int) -> list:
        mutated_grammars = []
        mutated_grammars = self.mutator.apply_rounds_of_mutations(self.grammar, num_mutations)
        return mutated_grammars
    

    def collect_npm_regexes(self) -> list:
        # exmaple: {"pattern": "[^a-zA-Z0-9\\/\\+=]", "supportedLangs": [], "type": "Regex", "useCount_IStype_to_nPosts": {}, "useCount_registry_to_nModules": {"npm": 2, "packagist": 15}}
        with open(self.FilePath, "r") as f:
            objs = f.readlines()
        data = [json.loads(obj) for obj in objs]
        regexes = [entry["pattern"] for entry in data if "npm" in entry["useCount_registry_to_nModules"]]
        return regexes

    #Rewrite it 
    def start(self, top_k = -1, num_mutations: int = 3) -> None:
        regex_list = self.collect_npm_regexes()
        stop_at = top_k if top_k > 0 else len(regex_list)
        generated_grammars = 0
        print(f"Total regexes to process: {len(regex_list)}")
        for regex in regex_list: #testing with the first 5 regexes 
            self.regex = regex
            try: 
                self.grammar, num_constraints = self.generate_grammar(self.regex)
                print(f"Processing regex: {self.regex}")
                print(f"Number of constraints generated: {num_constraints}")
                if self.constraints_only and num_constraints == 0:
                    print(f"Skipping regex {self.regex} as it has no constraints.")
                    continue
                self.mutation_count = 0 # reset mutation count for each regex
                self.current_output_dir = self.create_output_dir_for_regex()
                mutated_grammars = self.generate_mutated_grammars(num_mutations)
                self.write_fan_files(mutated_grammars)
                self.grammar = "" # reset grammar for next regex
                mutated_grammars = [] # reset mutated grammars for next regex
            except Exception as e:
                print(f"Error processing regex {self.regex}: {e}")
                continue

            generated_grammars += 1
            if generated_grammars >= stop_at:
                print(f"Reached top_k limit of {top_k}. Stopping generation.")
                self.cleanup()
                break

            #cleanup after each regex
            self.cleanup()
        with open(GENERATION_RECORD, "w") as record_file:
            json.dump(self.record, record_file, indent=2)
            print("Generation record saved.")
        


'''
def __main__():
    generator = regex_to_grammar_generator(regex="", FilePath=REGEXFILEPATH, num_grammars=num_grammars_to_generate_per_regex)
    generator.start(num_mutations=5)

if __name__ == "__main__":
    __main__()
'''

__all__ = ["regex_to_grammar_generator"]
