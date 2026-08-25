import fandango

# regex: \n\/[*/][@#]\s+sourceMappingURL=((?:(?!\s+\*\/).)*).*

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= "\n" "/" <r0> <r1> (<r2>)+ "s" "o" "u" "r" "c" "e" "M" "a" "p" "p" "i" "n" "g" "U" "R" "L" "=" (<r3> <byte>)* (<byte>)*

<r0> ::= r'[*\/]'
<r1> ::= r'[@#]'
<r2> ::= r'[ \t\n\r\f\v]'
<r3> ::= <byte>* := r3_generator()
  where lookahead_0(str(<r3>)) is True

# Constraints:

# Lookahead/Lookbehind constraint functions

def lookahead_0(b):
    """Negative lookahead: must NOT match r'[]'+\*/"""
    return not lookahead_0_match(b)

def lookahead_0_match(b):
    """Match pattern with full type validation"""
    # Validate repetition {1,MAXREPEAT}
    return r3_parses_with_subspec(b)

# Generators:

r3_OPENED = False
r3_fandango_instance = None
r3_cached_results = None
r3_pos_counter = 0

r3_fan_content = """
# regex: [(MAX_REPEAT, (1, MAXREPEAT, [(IN, [(CATEGORY, CATEGORY_SPACE)])])), (LITERAL, 42), (LITERAL, 47)]

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= (<r10>)+ "*" "/"

<r10> ::= r'[ \\t\\n\\r\\f\\v]'

# Constraints:

# No constraints


# Generators:


"""

def r3_generator():
    global r3_OPENED, r3_fandango_instance, r3_cached_results, r3_pos_counter
    # Ask a sub-instance of Fandango to generate names.
    # Caching for efficiency
    if not r3_OPENED:
        r3_fandango_instance = fandango.Fandango(r3_fan_content, use_cache=False)
        r3_cached_results = r3_fandango_instance.fuzz(desired_solutions=100, max_generations=100)
        r3_OPENED = True
    result = str(r3_cached_results[r3_pos_counter]) # Return the next name in the cached results, and loop back to the beginning when we reach the end
    r3_pos_counter = (r3_pos_counter + 1) % len(r3_cached_results)
    return result

def r3_parses(tree_as_str):
    global r3_OPENED, r3_fandango_instance
    if not r3_OPENED:
        r3_fandango_instance = fandango.Fandango(r3_fan_content, use_cache=False)
        r3_OPENED = True
    try:
        r3_fandango_instance.parse(tree_as_str)
    except Exception:
        return False
    return True