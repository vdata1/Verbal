import fandango

<start> ::= '__' <back_ref_to_me> '__' <deg>* '//' <capture_group> '//' ;
<back_ref_to_me> ::= <abc>* <abc_e> ;
<abc_e> ::= <abc> | '' ;
<abc> ::= 'a' | 'b' | 'c' ;
<deg> ::= 'd' | 'e' | 'g' ;
<capture_group> ::= <cgs> <cgf> ;
<cgs> ::= <abc> | '' ;
<cgf> ::= <byte>* ;

where str(<cgs>) == str(<abc_e>) ;

SUBSPEC = """
<start> ::= <ssabc> ;
<ssabc> ::= <abc>* ;
<abc> ::= 'a' | 'b' | 'c' ;
"""

OPENED = False
fandango_instance = None

def parse_capture_group(the_group, the_ref):
    global OPENED, fandango_instance
    if not OPENED:
        fandango_instance = fandango.Fandango(SUBSPEC, use_cache=False)
        OPENED = True
    try:
        the_group_str = str(the_group)
        the_ref_str = str(the_ref)
        parse_result = fandango_instance.parse(the_group_str)
        for tree in parse_result:
            print("Tree g:")
            print(tree)
        parse_result_the_ref = fandango_instance.parse(the_ref_str)
        for tree in parse_result_the_ref:
            print("Tree r:")
            print(tree)
    except Exception:
        return False
    return True