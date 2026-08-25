import fandango

# regex: (?:x(?:...|(...))\1x)+

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= <rs>+

<rs> ::= "x" (<r0> | <r1>) <r3> "x"
<r0> ::= <byte> <byte> <byte>
<r2> ::= <byte> <byte> <byte>
<r1> ::= <r2>
<r3> ::= <byte> <byte> <byte>

# Constraints:

# where all(item[2] == str(find_last_sub_nt_up_to(<start>, "<r1>", item[2])) for item in *<rs>)

def find_last_sub_nt_up_to(tree, target_nt, limit, current=None):
    if tree is limit:
        print("Happened.")
        return current
    if str(tree.symbol) == target_nt:
        current = tree
    for child in tree.children:
        result = find_last_sub_nt_up_to(child, target_nt, limit)
        if result is not None:
            return result
    return current