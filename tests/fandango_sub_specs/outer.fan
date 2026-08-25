from inner import gen_name, parses_with_subspec

<start> ::= <age> ", " <name> ;
<age> ::= <digit>+ ;
<name> ::= <char>* := gen_name() ;

where parses_with_subspec(<name>)