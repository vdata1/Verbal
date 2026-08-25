<start> ::= <regex>
<regex> ::= "/" <pattern> "/" <flags>?
<flags> ::= <flag>+
<flag> ::= "g" | "i" | "m" | "s" | "u" | "y"

<pattern> ::= <disjunction>
<disjunction> ::= <alternative> ("|" <alternative>)*
<alternative> ::= <term>*

<term> ::= <assertion> | <atom> <quantifier>?
<assertion> ::= "^" 

<quantifier> ::= "*" | "+" 
<atom> ::= <literal> | <character>  
<literal> ::= <character>+
<character_class> ::= "[" "^"? <class_atom>* "]"
<class_atom> ::= <character> | "\\" <atom_escape>

<atom_escape> ::= <character_class_escape> | <decimal_escape> | <identity_escape>
<character_class_escape> ::= "d" | "D" | "w" | "W" | "s" | "S" 
<decimal_escape> ::= "0"|"1"|"2"|"3"|"4"|"5"|"6"|"7"|"8"|"9"
<identity_escape> ::= "!" | "\"" | "#" | "%" | "&" | "'" | "(" | ")" | "*" | "+" | "," | "-" | "." | "/" | ":" | ";" | "<" | "=" | ">" | "?" | "@" | "[" | "]" | "^" | "_" | "`" | "{" | "|" | "}" | "~" | "A" | "B" | "C" | "E" | "F" | "G" | "H" | "I" | "J" | "K" | "L" | "M" | "N" | "O" | "P" | "Q" | "R" | "T" | "U" | "V" | "X" | "Y" | "Z" | "a" | "e" | "g" | "h" | "i" | "j" | "l" | "m" | "o" | "p" | "q" | "u" | "x" | "y" | "z" | <character>
<character> ::= "A"|"B"|"C"|"D"|"E"|"F"|"G"|"H"|"I"|"J"|"K"|"L"|"M"|"N"|"O"|"P"|"Q"|"R"|"S"|"T"|"U"|"V"|"W"|"X"|"Y"|"Z"|"a"|"b"|"c"|"d"|"e"|"f"|"g"|"h"|"i"|"j"|"k"|"l"|"m"|"n"|"o"|"p"|"q"|"r"|"s"|"t"|"u"|"v"|"w"|"x"|"y"|"z"|<ascii_uppercase_letter>|<ascii_lowercase_letter> 