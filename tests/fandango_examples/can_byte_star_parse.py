import fandango

STRING_TO_PARSE = "᥇"

spec_string = """
<start> ::= <byte>* ;
"""

if __name__ == "__main__":
    try:
        fandango_instance = fandango.Fandango(spec_string, use_cache=False)
        # Convert the string to bytes
        # Required for <byte>* parsing in Fandango, apparently
        my_string = STRING_TO_PARSE.encode('utf-8') 
        result = fandango_instance.parse(my_string)
        print("Parsed successfully! Here are the parse trees:")
        for tree in result:
            print("---")
            print(tree)
    except Exception as e:
        print(f"Error parsing string: {e}")