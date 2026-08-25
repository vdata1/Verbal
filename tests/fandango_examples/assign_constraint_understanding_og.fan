def copy_lhs(tree):
    lhs = tree.parent[0]
    return str(lhs)

def what(tree):
    return str(tree)

<start> ::= <item> 
<item> ::= <lhs> " -- " <rhs>
<lhs> ::= <cchar> <cchar> <cchar>
<rhs> ::= <cchar> <cchar> <cchar> := what(<lhs>)
<cchar> ::= "a" | "b" | "c"

