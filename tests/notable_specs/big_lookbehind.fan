import fandango

# regex: ^(?=((?:[^"']+|"[^"\\]*(?:\\[^][^"\\]*)*"|'[^'\\]*(?:\\[^][^'\\]*)*')*))\1.

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= "" <r0> <r18> <byte>

<r5> ::= r'[^\"\']'
<r4> ::= <r5>
<r3> ::= (<r4>)+
<r8> ::= r'[^\"\\]'
<r7> ::= <r8>
<r11> ::= r'[^][^\"\\]'
<r10> ::= <r11>
<r9> ::= "\\" (<r10>)*
<r6> ::= "\"" (<r7>)* (<r9>)* "\""
<r14> ::= r'[^\'\\]'
<r13> ::= <r14>
<r17> ::= r'[^][^\'\\]'
<r16> ::= <r17>
<r15> ::= "\\" (<r16>)*
<r12> ::= "\'" (<r13>)* (<r15>)* "\'"
<r2> ::= (<r3> | <r6> | <r12>)
<r1> ::= (<r2>)*
<r0> ::= <r0_e> <byte>*
<r0_e> ::= <r1> | ""
<r18> ::= (<r2>)*

# Constraints:

# Constraints

where <r0_e> != ""

# Capture group reference constraints

where has_preceeding_group("<r1>", <r18>)
where all(<item> == str(latest_matched_group("<r1>", <item>)) for <item> in *<r18>)

# Generators:


def has_preceeding_group(target_nt, tree):
    # look for target_nt
    possible = latest_matched_group(target_nt, tree)
    if possible is None:
        return False
    return True

def latest_matched_group(target_nt, target_node):
    # For debug purposes, lets print
    # Go all the way up
    parentt = target_node
    while parentt.parent is not None:
        parentt = parentt.parent
    all_matches_gen = parentt.find_subtrees(target_nt, stop_at=target_node, bfs_mode=False)
    last_match = None
    for matchh in all_matches_gen:
        last_match = matchh # Get the last match
    # Make sure it returns None, not str(None) lol
    if last_match is None:
        return None
    return str(last_match)