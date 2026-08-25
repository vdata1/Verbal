# provenance:
#   git_commit: 48defb5d8769b2ef2d7281b081b5277867f18115
#   config_sha: d769e16a7cda2f6d72eb588b3dd1b24c8759cce2d09f453fd00753e4632790bd
#   seed: 0
#   corpus: data/uniq-regexes-8.json
#   corpus_sha: 999fe71e83f0db26931d6810164bff9efefdf3f6791d3444aa770ccdafe280e9
#   stage: base_spec
#   regex_id: regex_5354
# meta: capture_group_rules=<r0>,<r2>,<r19>
# meta: regex_facts={"anchored_single_match": false, "requires_flags": [], "unsatisfiable_internal_anchor": false}

# regex: (.+)\\n(\\d{2}:\\d{2}:\\d{2},\\d{3} --> \\d{2}:\\d{2}:\\d{2},\\d{3})\\n((?:^.*$\\n)*?)\\n

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= <r0> "\n" <r2> "\n" <r19> "\n"

<r1> ::= r'[\x00-\x09\x0b\x0c\x0e-\x7f]'
<r0> ::= (<r1>)+
<r4> ::= r'[0-9]'
<r3> ::= <r4>
<r6> ::= r'[0-9]'
<r5> ::= <r6>
<r8> ::= r'[0-9]'
<r7> ::= <r8>
<r10> ::= r'[0-9]'
<r9> ::= <r10>
<r12> ::= r'[0-9]'
<r11> ::= <r12>
<r14> ::= r'[0-9]'
<r13> ::= <r14>
<r16> ::= r'[0-9]'
<r15> ::= <r16>
<r18> ::= r'[0-9]'
<r17> ::= <r18>
<r2> ::= (<r3>){2} ":" (<r5>){2} ":" (<r7>){2} "," (<r9>){3} " " "-" "-" ">" " " (<r11>){2} ":" (<r13>){2} ":" (<r15>){2} "," (<r17>){3}
<r21> ::= r'[\x00-\x09\x0b\x0c\x0e-\x7f]'
<r20> ::= "" (<r21>)* "" "\n"
<r19> ::= (<r20>)*

# Constraints:

# No lookaround constraints


# Generators:

