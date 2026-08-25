import fandango

<start> ::= <r0> <r0_la> ;

<r0> ::= "foo" ;

<r0_la> ::= <la> <rest>* ;

<la> ::= "b" | "" ;

<rest> ::= "a" | "b" | "c" ;

# Not sufficient by itself actually.
where <la> == "" ;

where not reparse(<start>) ;

def reparse(tree):
    with open("./correct_negative_lookahead_no_reparse.fan", "r") as f:
        fan_spec = f.read();
    reparse_instance = fandango.Fandango(fan_spec, use_cache = False)
    trees = reparse_instance.parse(str(tree))
    # print("---------")
    num_t = 0
    for tree in trees:
        # print(f"tree: {tree.to_tree()}")
        num_t = num_t + 1
    return num_t > 1