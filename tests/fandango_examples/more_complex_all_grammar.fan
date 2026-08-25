<start> ::= (<item> ", ") <item>
<item> ::= <lhs> " -- " <rhs>
<lhs> ::= <cchar> <cchar> <cchar>
<rhs> ::= <cchar> <cchar> <cchar>
<cchar> ::= "a" | "b" | "c" | "d" | "e" | "f" | "g" | "h" | "i" | "j" | "k" | "l" | "m" | "n" | "o" | "p" | "q" | "r" | "s" | "t" | "u" | "v" | "w" | "x" | "y" | "z"

where all([str(e) for e in item.find_subtrees("<lhs>")] == [str(e) for e in item.find_subtrees("<rhs>")] for item in *<item>)