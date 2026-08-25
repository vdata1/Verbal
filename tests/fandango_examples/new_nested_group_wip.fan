import fandango

# regex: (?:x(?:...|(...))\1x)+

# Grammar:

# Generated EBNF Grammar for Fandango Fuzzer

<start> ::= <rs>+

<rs> ::= "x" (<r0> | <r1>) <r3> "x"
<r0> ::= <bytee> <bytee> <bytee>
<r2> ::= <bytee> <bytee> <bytee>
<r1> ::= <r2>
<r3> ::= <bytee> <bytee> <bytee>

<bytee> ::= "a" | "b" | "c"

where has_preceeding_group("<r1>", <r3>)
where all(item == str(latest_matched_group("<r1>", item)) for item in *<r3>)

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
    if last_match is None:
        return None
    return str(last_match)