import fandango

# regex: \b(bool|byte|complex(64|128)|float(32|64)|func|interface|map|rune|string|struct|u?int(8|16|32|64)?|var)(?=\b)

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= "" <r0> <r26>

<r1> ::= "b" "o" "o" "l"
<r2> ::= "b" "y" "t" "e"
<r5> ::= "6" "4"
<r6> ::= "1" "2" "8"
<r4> ::= (<r5> | <r6>)
<r3> ::= "c" "o" "m" "p" "l" "e" "x" <r4>
<r9> ::= "3" "2"
<r10> ::= "6" "4"
<r8> ::= (<r9> | <r10>)
<r7> ::= "f" "l" "o" "a" "t" <r8>
<r11> ::= "f" "u" "n" "c"
<r12> ::= "i" "n" "t" "e" "r" "f" "a" "c" "e"
<r13> ::= "m" "a" "p"
<r14> ::= "r" "u" "n" "e"
<r15> ::= "s" "t" "r" "i" "n" "g"
<r16> ::= "s" "t" "r" "u" "c" "t"
<r18> ::= "u"
<r21> ::= "8"
<r22> ::= "1" "6"
<r23> ::= "3" "2"
<r24> ::= "6" "4"
<r20> ::= (<r21> | <r22> | <r23> | <r24>)
<r19> ::= <r20>
<r17> ::= (<r18>)? "i" "n" "t" (<r19>)?
<r25> ::= "v" "a" "r"
<r0> ::= (<r1> | <r2> | <r3> | <r7> | <r11> | <r12> | <r13> | <r14> | <r15> | <r16> | <r17> | <r25>)
<r26> ::= <r26_e> <byte>*
<r26_e> ::= "" | ""

# Constraints:

# Constraints

where <r26_e> != ""

# Generators:


