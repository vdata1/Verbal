import re
import random
from dataclasses import dataclass
from typing import List


MAXRAND = 1000000
# ----------------------------
# Quantifier representation
# ----------------------------

@dataclass
class Quantifier:
    start: int
    end: int
    text: str

# ----------------------------
# Regex patterns
# ----------------------------


class Mutator: 
    def __init__(self):

        # Order matters: longest first
        self.QUANTIFIER_PATTERNS = [
            r"\{\s*\d+\s*,\s*\d+\s*\}",   # {x,y}
            r"\{\s*\d+\s*,\s*\}",         # {x,}
            r"\{\s*,\s*\d+\s*\}",         # {,y}
            r"\{\s*\d+\s*\}",             # {x}
            r"\+(?!=\'|\")",              # + (avoid mutation on normal + character inside character classes)
            r"\*(?!=\'|\")",              # * (avoid mutation on normal * character inside character classes)
            r"\?(?!=|!|<!|<=|:)",         # ? (not followed by "=", "!", "<!", "<=", ":" to avoid mutations on lookaheads and non-capturing groups expressions)
            r"\|"                         # | (added to allow mutation of alternation operators)   
        ]

        self.QUANTIFIER_RE = re.compile("|".join(self.QUANTIFIER_PATTERNS))
        self.quantifiers = []
        self.regex = "" 
        self.grammar = "" 
    # ----------------------------
    # Quantifier extraction
    # ----------------------------
    def cleanup(self):
        pass 

    def extract_quantifiers(self, grammar: str) -> List[Quantifier]:
        self.quantifiers = []
        self.constraints = []
        self.regex = ""
        cpgrammar = []

        
        for line in grammar.split("\n"):
            #line = line.strip()
            
            if not line:
                continue
            
            if line.startswith("#regex:"):
                self.regex = line
            elif "_e> ::=" in line: # These are regex constraint lines, so keep them separate.
                self.constraints.append(line)
            elif "> ::=" in line:
                cpgrammar.append(line)
            elif not line.startswith("#") and not line.startswith(" #") and line != " ":
                self.constraints.append(line)

        cpgrammar = "\n".join(cpgrammar)
        
        for m in self.QUANTIFIER_RE.finditer(cpgrammar):
            #print(f"Found quantifier: {m.group(0)} at positions {m.start()}-{m.end()}")
            self.quantifiers.append(
                Quantifier(
                    start=m.start(),
                    end=m.end(),
                    text=m.group(0)
                )
            )

        self.grammar = cpgrammar
        #print(f"Extracted quantifiers: {[q.text for q in quantifiers]}")
        return self.quantifiers


    # ----------------------------
    # Mutation helpers
    # ----------------------------

    def clamp(self, n: int) -> int:
        return max(0, n)

    def random_delta(self,max_delta=random.randint(1, MAXRAND)) -> int:
        return random.randint(1, max_delta)

    # ----------------------------
    # Mutation logic
    # ----------------------------

    def mutate_quantifier(self, q: str) -> str:
        q = q.strip()

        # ----- Symbolic quantifiers -----
        if q == "*":
            return random.choice(["+", "?", f"{{0,{self.random_delta()}}}"]) #, f"{{{self.random_delta()},}}"]) #, "*?"])  # adding non-greedy variant

        if q == "+":
            return random.choice(["*",  f"{{{1},{1 + self.random_delta()}}}"]) #, f"{{{1 + self.random_delta()},}}"]) #, "+?"])  # adding non-greedy variant

        if q == "?":
            return random.choice(["*", "{0,1}"]) #, "?{1}"])  # adding non-greedy variant
        if q == "|": 
            return random.choice([""]) # change OR with AND, add more mutations, if possible 

        # ----- Bounded quantifiers -----
        nums = list(map(int, re.findall(r"\d+", q)))

        # {x}
        if re.fullmatch(r"\{\s*\d+\s*\}", q):
            x = nums[0]
            return random.choice([
                f"{{{self.clamp(x + self.random_delta())}}}",
                f"{{{self.clamp(x - self.random_delta())}}}",
                f"{{{x},{x + self.random_delta()}}}"
            ])

        # {x,y}
        if re.fullmatch(r"\{\s*\d+\s*,\s*\d+\s*\}", q):
            x, y = nums
            if x > y:
                x, y = y, x
            return random.choice([
                f"{{{x},{y + self.random_delta()}}}",        # widen upper
                f"{{{self.clamp(x - self.random_delta())},{y}}}", # widen lower
               # f"{{{x},}}",                            # unbound upper
                f"{{,{y}}}",                            # unbound lower
            ])

        # {x,}
        if re.fullmatch(r"\{\s*\d+\s*,\s*\}", q):
            x = nums[0]
            return random.choice([
               # f"{{{self.clamp(x - self.random_delta())},}}",
                f"{{{x},{x + self.random_delta()}}}",
                "*"
            ])

        # {,y}
        if re.fullmatch(r"\{\s*,\s*\d+\s*\}", q):
            y = nums[0]
            return random.choice([
                f"{{0,{y + self.random_delta()}}}",
                f"{{,{self.clamp(y - self.random_delta())}}}",
                "?"
            ])

        return q  # fallback (should not happen)


    # ----------------------------
    # Grammar mutation driver
    # ----------------------------

    def mutate_grammar(self, max_mutations: int = 3) -> str:
        random.seed(0, 1000000) # for reproducibility    
        quantifiers = self.extract_quantifiers(self.grammar)

        if not quantifiers:
            return self.grammar

        grammar_chars = list(self.grammar)
        mutations = random.randint(1, min(max_mutations, len(quantifiers)))
        chosen = random.sample(quantifiers, mutations)

        # Apply from right to left to keep offsets valid
        for q in sorted(chosen, key=lambda x: x.start, reverse=True):
            new_q = self.mutate_quantifier(q.text)
            grammar_chars[q.start:q.end] = list(new_q)

        return "".join(grammar_chars)

    def apply_rounds_of_mutations(self, grammar: str, num_mutations: int) -> list: # Apply multiple rounds of mutations
        self.grammar = grammar
        new_grammars = []
        new_ebnf = "" 
        mutated_grammar = ""
        new_grammars.append(self.grammar)  # Include the original grammar
        for _ in range(num_mutations):
            mutated_grammar = self.mutate_grammar(max_mutations=1)
            if self.grammar != mutated_grammar:  # Only add if a mutation occurred
                self.grammar = mutated_grammar
                new_ebnf = "".join(self.regex + "\n" + self.grammar)
                if len(self.constraints) > 0 and self.constraints[0] != "" and self.constraints[0] != " ":

                    new_ebnf += "\n" + "\n".join(self.constraints)
                self.grammar = new_ebnf
                new_grammars.append(new_ebnf)
            else: 
                break  # Stop if no further mutations can be made
        return new_grammars 

# ----------------------------
# Example usage
# ----------------------------


# if __name__ == "__main__":
#     fandango_grammar = open("./test.fan").read()
#     # Make a mutator
#     mutator = Mutator()
#      # Apply mutations
#      # Note: we can apply multiple rounds of mutations to increase the chances of generating a grammar that leads to different behavior across runtimes, since one mutation might not be enough to trigger such differences.
#     mutated_grammars = mutator.apply_rounds_of_mutations(fandango_grammar, num_mutations=5)
#     print("Original grammar:\n", fandango_grammar)
#     for i, mutated_grammar in enumerate(mutated_grammars[1:], start=1):  # Skip the original grammar at index 0
#         print("----------------------------")
#         print(f"\nMutated grammar {i}:\n", mutated_grammar)


__all__ = [
    "Mutator",
    "apply_rounds_of_mutations", 
    "mutate_grammar",
    "extract_quantifiers", 
    "mutate_quantifier"
]

