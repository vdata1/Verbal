import fandango

OPENED = False
fandango_instance = None
cached_results = None
pos_counter = 0

fan_content = """
<start> ::= <inner_name> ;
<inner_name> ::= <char>+ ;
"""

def gen_name():
    global OPENED, fandango_instance, cached_results, pos_counter
    # Ask a sub-instance of Fandango to generate names.
    # Caching for efficiency
    if not OPENED:
        fandango_instance = fandango.Fandango(fan_content, use_cache=False)
        cached_results = fandango_instance.fuzz(desired_solutions=100, max_generations=100)
        OPENED = True
    result = str(cached_results[pos_counter]) # Return the next name in the cached results, and loop back to the beginning when we reach the end
    pos_counter = (pos_counter + 1) % len(cached_results)
    return result

def parses_with_subspec(tree):
    global OPENED, fandango_instance
    if not OPENED:
        fandango_instance = fandango.Fandango(fan_content, use_cache=False)
        OPENED = True
    tree_as_str = str(tree)
    try:
        fandango_instance.parse(tree_as_str)
    except Exception:
        return False
    return True