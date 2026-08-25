# regex: ((['"])(a|b|c)*(\2), )+

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= (<r0>)+

<r2> ::= r'[\'\"]'
<r1> ::= <r2>
<r4> ::= r'[abc]'
<r3> ::= <r4>
<r5> ::= <r2>
<r0> ::= <r1> (<r3>)* <r5> "," " "

def find_sub_nt(tree, target_nt):
    if str(tree.symbol) == target_nt:
        return tree
    for child in tree.children:
        result = find_sub_nt(child, target_nt)
        if result is not None:
            return result
    return None
    
def assert_group_equality_r1_r5(a):
    return str(find_sub_nt(a, "<r5>")) == str(find_sub_nt(a, "<r1>"))

where unholy_reference_equality(<r0>)




