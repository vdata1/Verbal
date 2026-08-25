import fandango

# Doesn't work for \n, \f, and \r.

parse_me = """
<start> ::= '\n'+ ;
"""

parse_me_but_in_a_file = './parse_me.fan'

parse_me_works = """
<start> ::= '\\n'+ ;
"""

if __name__ == "__main__":

    # This won't work, likely the inner parser interprets '\n' as a real newline.
    # If the spec is in a different file, though, it works fine.
    try:
        fandango_instance = fandango.Fandango(parse_me, use_cache=False)
    except Exception as e:
        print(f"Error parsing or fuzzing parse_me: {e}")

    # This works
    with open(parse_me_but_in_a_file, "r") as f:
        content = f.read()
        fandango_instance_from_file = fandango.Fandango(content, use_cache=False)

    # This works
    fandango_instance_works = fandango.Fandango(parse_me_works, use_cache=False)