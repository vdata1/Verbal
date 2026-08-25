# regex: (['"])(a|b|c)*(\1)

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= <r0> (<r2>)* <r4>

<r1> ::= r'[\'\"]'
<r0> ::= <r1>
<r3> ::= r'[abc]'
<r2> ::= <r3>
<r5> ::= <r1>
<r4> ::= <r5>

# Constraints:

# Lookahead/Lookbehind constraint functions

def constraint_r5_equals_r0(a, b):
    """Constraint to ensure <r5> equals <r0> for group reference"""
    return str(a) == str(b)


# Capture group reference constraints

where constraint_r5_equals_r0(<r5>, <r0>)

# Generators:
