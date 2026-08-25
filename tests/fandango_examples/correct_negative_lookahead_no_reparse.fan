import fandango

<start> ::= <r0> <r0_la> ;

<r0> ::= "foo" ;

<r0_la> ::= <la> <rest>* ;

<la> ::= "b" | "" ;

<rest> ::= "a" | "b" | "c" ;