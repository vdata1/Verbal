# regex: ^(?=.*[A-Z])(?=.*\d)[A-Za-z\d]{8,}$

import fandango

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= "" <r0> <r1> (<r2>){8,} ""

<r0> ::= <byte>* := r0_generator()
  where lookahead_0(str(<r0>))

<r1> ::= <byte>* := r1_generator()
  where lookahead_1(str(<r1>))

<r2> ::= r'[A-Za-z0-9]'

# Constraints:

# Lookahead/Lookbehind constraint functions

def lookahead_0(s, b):
    """Positive lookahead: must match .*r'[A-Z]'
    Validates both length and character content"""
    # Length constraint: b must have at least 0 characters
    if len(b) < 0:
        return False
    # Content validation: check if b matches the pattern
    return lookahead_0_match(b)

def lookahead_0_match(b):
    """Match pattern with full type validation"""
    # Validate repetition {0,MAXREPEAT}
    for i in range(0, len(b)):
        if len(b) - 0 < 0:
            return False
    return True


def lookahead_1(s, b):
    """Positive lookahead: must match .*r'[]'
    Validates both length and character content"""
    # Length constraint: b must have at least 0 characters
    if len(b) < 0:
        return False
    # Content validation: check if b matches the pattern
    return lookahead_1_match(b)

def lookahead_1_match(b):
    """Match pattern with full type validation"""
    # Validate repetition {0,MAXREPEAT}
    for i in range(0, len(b)):
        if len(b) - 0 < 0:
            return False
    return True


# Generators:


r0_OPENED = False
r0_fandango_instance = None
r0_cached_results = None
r0_pos_counter = 0

r0_fan_content = """
# regex: [(MAX_REPEAT, (0, MAXREPEAT, [(ANY, None)])), (IN, [(RANGE, (65, 90))])]

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= (<byte>)* <r0>

<r0> ::= r'[A-Z]'

# Constraints:

# No constraints


# Generators:


"""

def r0_generator():
    global r0_OPENED, r0_fandango_instance, r0_cached_results, r0_pos_counter
    # Ask a sub-instance of Fandango to generate names.
    # Caching for efficiency
    if not r0_OPENED:
        r0_fandango_instance = fandango.Fandango(r0_fan_content, use_cache=False)
        r0_cached_results = r0_fandango_instance.fuzz(desired_solutions=100, max_generations=100)
        r0_OPENED = True
    result = str(r0_cached_results[r0_pos_counter]) # Return the next name in the cached results, and loop back to the beginning when we reach the end
    r0_pos_counter = (r0_pos_counter + 1) % len(r0_cached_results)
    return result
        


r1_OPENED = False
r1_fandango_instance = None
r1_cached_results = None
r1_pos_counter = 0

r1_fan_content = """
# regex: [(MAX_REPEAT, (0, MAXREPEAT, [(ANY, None)])), (IN, [(CATEGORY, CATEGORY_DIGIT)])]

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= (<byte>)* <r0>

<r0> ::= r'[0-9]'

# Constraints:

# No constraints


# Generators:


"""

def r1_generator():
    global r1_OPENED, r1_fandango_instance, r1_cached_results, r1_pos_counter
    # Ask a sub-instance of Fandango to generate names.
    # Caching for efficiency
    if not r1_OPENED:
        r1_fandango_instance = fandango.Fandango(r1_fan_content, use_cache=False)
        r1_cached_results = r1_fandango_instance.fuzz(desired_solutions=100, max_generations=100)
        r1_OPENED = True
    result = str(r1_cached_results[r1_pos_counter]) # Return the next name in the cached results, and loop back to the beginning when we reach the end
    r1_pos_counter = (r1_pos_counter + 1) % len(r1_cached_results)
    return result
