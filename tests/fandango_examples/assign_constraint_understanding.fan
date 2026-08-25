<start> ::= (<item> ", ")+ <item>
<item> ::= <lhs> " -- " <rhs>
<lhs> ::= <cchar> <cchar> <cchar>
<rhs> ::= <cchar> <cchar> <cchar>
<cchar> ::= "a" | "b" | "c"

where all(item[2] == str(find_last_sub_nt_up_to(<start>, "<lhs>", item[2])) for item in *<item>)

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