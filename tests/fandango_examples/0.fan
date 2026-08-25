import fandango

<start> ::= (<r0>)+
<r0> ::= <byte>* := r3_generator()

r3_OPENED = False
r3_fandango_instance = None
r3_cached_results = None
r3_pos_counter = 0

r3_fan_content = """
<start> ::= (<r10>)+ "*" "/"
<r10> ::= r'[ \\t\\n\\r\\f\\v]'
"""

def r3_generator():
    global r3_OPENED, r3_fandango_instance, r3_cached_results, r3_pos_counter
    # Ask a sub-instance of Fandango to generate names.
    # Caching for efficiency
    if not r3_OPENED:
        r3_fandango_instance = fandango.Fandango(r3_fan_content, use_cache=False, logging_level=10)
        r3_cached_results = r3_fandango_instance.fuzz(desired_solutions=100, max_generations=100)
        r3_OPENED = True
    result = str(r3_cached_results[r3_pos_counter]) # Return the next name in the cached results, and loop back to the beginning when we reach the end
    r3_pos_counter = (r3_pos_counter + 1) % len(r3_cached_results)
    return result

def r3_parses_with_subspec(tree_as_str):
    global r3_OPENED, r3_fandango_instance
    if not r3_OPENED:
        r3_fandango_instance = fandango.Fandango(r3_fan_content, use_cache=False)
        r3_OPENED = True
    try:
        r3_fandango_instance.parse(tree_as_str)
    except Exception:
        return False
    return True