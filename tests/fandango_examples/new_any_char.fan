import fandango

# regex: (?=^\d{2}:\d{2}:\d{2}\.\d+ \(\d+\)\|)

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= <r0>

<r2> ::= r'[0-9]'
<r1> ::= <r2>
<r4> ::= r'[0-9]'
<r3> ::= <r4>
<r6> ::= r'[0-9]'
<r5> ::= <r6>
<r8> ::= r'[0-9]'
<r7> ::= <r8>
<r10> ::= r'[0-9]'
<r9> ::= <r10>
<r0> ::= <r0_e> <utf8_char>*
<r0_e> ::= "" (<r1>){2} ":" (<r3>){2} ":" (<r5>){2} "." (<r7>)+ " " "(" (<r9>)+ ")" "|" | ""

# Constraints:

# Constraints

where <r0_e> != ""

# Generators:
