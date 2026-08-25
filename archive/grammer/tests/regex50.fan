<start> ::= <regex>{50}
<regex> ::= "/" <pattern> "/" <flags>?
<flags> ::= <flag>+
<flag> ::= "g" | "i" | "m" | "s" | "u" | "y"

<pattern> ::= <disjunction>
<disjunction> ::= <alternative> ("|" <alternative>)*
<alternative> ::= <term>*

<term> ::= <assertion> | <atom> <quantifier>?
<assertion> ::= "^" | "$" | "\\b" | "\\B" | "(?=" <disjunction> ")" | "(?!" <disjunction> ")"

<quantifier> ::= "*" | "+" | "?" | "{" <digits> ("," <digits>?)? "}"
<digits> ::= <decimal_escape>+
<atom> ::= <literal> | <character> | "." | "\\" <atom_escape> | <character_class> | "(" <group> ")"
<literal> ::= <character>+
<group> ::= "(?:" <disjunction> ")" | <disjunction>
<character_class> ::= "[" "^"? <class_atom>* "]"
<class_atom> ::= <character> | "\\" <atom_escape>

<atom_escape> ::= <character_class_escape> | <decimal_escape> | <identity_escape>
<character_class_escape> ::= "d" | "D" | "w" | "W" | "s" | "S" 
<decimal_escape> ::= "٠"|"١"|"٢"|"٣"|"٤"|"٥"|"٦"|"٧"|"٨"|"٩"
<identity_escape> ::= "!" | "\"" | "#" | "%" | "&" | "'" | "(" | ")" | "*" | "+" | "," | "-" | "." | "/" | ":" | ";" | "<" | "=" | ">" | "?" | "@" | "[" | "]" | "^" | "_" | "`" | "{" | "|" | "}" | "~" | "A" | "B" | "C" | "E" | "F" | "G" | "H" | "I" | "J" | "K" | "L" | "M" | "N" | "O" | "P" | "Q" | "R" | "T" | "U" | "V" | "X" | "Y" | "Z" | "a" | "e" | "g" | "h" | "i" | "j" | "l" | "m" | "o" | "p" | "q" | "u" | "x" | "y" | "z" | <character>

<character> ::= "ء"|"آ"|"أ"|"ؤ"|"إ"|"ئ"|"ا"|"ب"|"ة"|"ت"|"ث"|"ج"|"ح"|"خ"|"د"|"ذ"|"ر"|"ز"|"س"|"ش"|"ص"|"ض"|"ط"|"ظ"|"ع"|"غ"|"ف"|"ق"|"ك"|"ل"|"م"|"ن"|"ه"|"و"|"ى"|"ي"|"ٱ"|"پ"|"چ"|"ژ"|"ڤ"|"گ"|"ں"|"ھ"|"ہ"|"ۂ"|"ۀ"|"ی"|"ے"|"ۍ"|"ێ"|"ې"|"ۏ"|"ۋ"|"ۆ"|"ۇ"|"ۈ"|"ۉ"|"ۊ"|"ۓ"|"ٹ"|"ٺ"|"ٻ"|"ټ"|"ٽ"|"ٿ"|"ڀ"|"ځ"|"ڂ"|"ڄ"|"څ"|"ڇ"|"ڈ"|"ډ"|"ڊ"|"ڋ"|"ڌ"|"ڍ"|"ڎ"|"ڏ"|"ڐ"|"ڑ"|"ڒ"|"ڙ"|"ږ"|"ڗ"|"ښ"|"ڛ"|"ڜ"|"ڝ"|"ڞ"|"ڟ"|"ڠ"|"ڡ"|"ڢ"|"ڣ"|"ڥ"|"ڦ"|"ڧ"|"ڨ"|"ڪ"|"ګ"|"ڬ"|"ڭ"|"ڮ"|"ڰ"|"ڱ"|"ڲ"|"ڳ"|"ڴ"|"ڵ"|"ڶ"|"ڷ"|"ڸ"|"ڹ"|"ڻ"|"ڼ"|"ڽ"|"ۥ"|"ۦ"|"ݐ"|"ݑ"|"ݒ"|"ݓ"|"ݔ"|"ݕ"|"ݖ"|"ݗ"|"ݘ"|"ݙ"|"ݚ"|"ݛ"|"ݜ"|"ݝ"|"ݞ"|"ݟ"|"ݠ"|"ݡ"|"ݢ"|"ݣ"|"ݤ"|"ݥ"|"ݦ"|"ݧ"|"ݨ"|"ݩ"|"ݪ"|"ݫ"|"ݬ"|"ݭ"|"ݮ"|"ݯ"|"ݰ"|"ݱ"|"ݲ"|"ݳ"|"ݴ"|"ݵ"|"ݶ"|"ݷ"|"ݸ"|"ݹ"|"ݺ"|"ݻ"|"ݼ"|"ݽ"|"ݾ"|"ݿ"|<ascii_uppercase_letter>|<ascii_lowercase_letter> 
