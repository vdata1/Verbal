import fandango

# regex: (?:\n\n)([ ]{0,3}(?:<([?%])[^\r]*?\2>)[ \t]*(?=\n{2,}))

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= "\n" "\n" <r0>

<r1> ::= " "
<r3> ::= r'[?%]'
<r2> ::= <r3>
<r5> ::= r'[^\r]'
<r4> ::= <r5>
<r6> ::= <r3>
<r8> ::= r'[ \t]'
<r7> ::= <r8>
<r10> ::= "\n"
<r9> ::= <r9_e> <byte>*
<r9_e> ::= (<r10>){2,} | ""
<r0> ::= (<r1>){0,3} "<" <r2> (<r4>)* <r6> ">" (<r7>)* <r9>

# Constraints:

# Constraints

where <r9_e> != ""

# Capture group reference constraints

where has_preceeding_group("<r2>", <r6>)
where all(<item> == str(latest_matched_group("<r2>", <item>)) for <item> in *<r6>)

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