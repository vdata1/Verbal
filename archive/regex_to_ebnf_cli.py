import sre_parse
import sre_constants
import re

def new_non_terminal(base_nt, counter):
    """Generate a new unique non-terminal symbol."""
    name = f"{base_nt}{counter[0]}"
    #print("Generated new non-terminal:", name)
    counter[0] += 1
    return name

def def_non_terminal_repeat(base_nt, repeat):
    """Define a non-terminal for a repeated pattern."""
    name = f"'{base_nt}'{repeat}"
    return name

def escape_char(c):
    """Escape single quotes and backslashes for EBNF output."""
    if c == "'": return "\\'"
    if c == "\\": return "\\\\"
    return c

def convert_token(token, base_nt, counter, non_terminals):
    """Convert a regex token (opcode, args) to EBNF rules."""
    opcode, arg = token
    start = new_non_terminal(base_nt, counter)
    end = new_non_terminal(base_nt, counter)
    non_terminals.update([start, end])
    rules = []
    #print("Converting token:", opcode, arg)
    if opcode == sre_constants.LITERAL:
        char = chr(arg)
        rules.append((start, [char, end]))
        
    elif opcode in (sre_constants.REPEAT, sre_constants.MIN_REPEAT, sre_constants.MAX_REPEAT):
        min_cnt, max_cnt, item = arg
        #print(f"Handling repeat: min={min_cnt}, max={max_cnt}, item={item}")
        # Check if the repeated item is a single literal and avoid further tokenization if so
        if len(item) == 1 and item[0][0] == sre_constants.LITERAL:
            # Single literal repeated, do not process it again in parent sequence
            #print("Single literal repeat optimization:", item)
            literal = chr(item[0][1])
            if max_cnt == sre_constants.MAXREPEAT:
                rep_str = f"{{{min_cnt},}}"
            elif min_cnt == max_cnt:
                rep_str = f"{{{min_cnt}}}"
            else:
                rep_str = f"{{{min_cnt},{max_cnt}}}"
            repeat = def_non_terminal_repeat(literal, rep_str)
            rules.append((start, [repeat, end]))
        else:
            exp_start, exp_end, exp_rules = convert_parsed(item, base_nt, counter, non_terminals)
            rules.extend(exp_rules)

            if min_cnt == 0 and max_cnt == sre_constants.MAXREPEAT:  # *
                # Kleene star: 0 or more
                rules.extend([(start, [end]), (start, [exp_start]),
                            (exp_end, [start]), (exp_end, [end])])
            elif min_cnt == 1 and max_cnt == sre_constants.MAXREPEAT:  # +
                # One or more
                rules.extend([(start, [exp_start]), (exp_end, [start]), (exp_end, [end])])
            elif min_cnt == 0 and max_cnt == 1:  # ?
                # Optional: 0 or 1
                rules.extend([(start, [end]), (start, [exp_start]), (exp_end, [end])])
            else:
                # {n}, {n,}, {,m}, or {n,m}
                if max_cnt == sre_constants.MAXREPEAT:
                    # At least min_cnt
                    rep_str = f"{{{min_cnt},}}"
                elif min_cnt == max_cnt:
                    # Exactly min_cnt
                    rep_str = f"{{{min_cnt}}}"
                elif min_cnt == 0:
                    # Up to max_cnt
                    rep_str = f"{{,{max_cnt}}}"
                else:
                    # Between min_cnt and max_cnt
                    rep_str = f"{{{min_cnt},{max_cnt}}}"

                # More complex, apply repetition to the nonterminal
                repeat = def_non_terminal_repeat(exp_start, rep_str)
                #print("Defining repeat non-terminal:", repeat)
                # Link start to the repetition
                rules.append((start, [repeat, end]))
            # Always link to end
            rules.append((exp_end, [end]))

            
    elif opcode in (sre_constants.BRANCH, sre_constants.SUBPATTERN):
         # print("Handling BRANCH/SUBPATTERN:", arg)
         # Handle branches (alternatives)
         # arg is (None, [list of branches])
         # Each branch is a list of tokens
         # For SUBPATTERN, arg is (group_num, subpattern)
         # We treat SUBPATTERN similarly to BRANCH for EBNF purposes
        branches = arg[1] if opcode == sre_constants.BRANCH else [arg[3]]
        for branch in branches:
            if not branch:
                # Empty branch (epsilon)
                rules.append((start, [end]))
            else:
                b_start, b_end, b_rules = convert_parsed(branch, base_nt, counter, non_terminals)
                rules.append((start, [b_start]))
                rules.append((b_end, [end]))
                rules.extend(b_rules)
            #b_start, b_end, b_rules = convert_parsed(branch, base_nt, counter, non_terminals)
            #rules.append((start, [b_start]))
            #rules.append((b_end, [end]))
            #rules.extend(b_rules)
            
   

    elif opcode == sre_constants.IN:
        #print("Handling IN:", arg)
         # Handle character classes
         # arg is a list of (opcode, arg) tuples
         # e.g., [(LITERAL, 97), (LITERAL, 98)]
         # e.g., [(LITERAL, 97), (RANGE, (98, 100))]
         # e.g., [(CATEGORY, CATEGORY_DIGIT)]
        chars = set()
        for item in arg:
            if item[0] == sre_constants.LITERAL:
                chars.add(chr(item[1]))
            elif item[0] == sre_constants.RANGE:
                low, high = item[1]
                chars.update(chr(c) for c in range(low, high + 1))
            elif item[0] == sre_constants.CATEGORY:
                # Handle character categories like \d, \w, etc.
                if item[1] == sre_constants.CATEGORY_DIGIT:
                    chars.update(str(i) for i in range(10))
                elif item[1] == sre_constants.CATEGORY_WORD:
                    chars.update(chr(c) for c in range(65, 91))  # A-Z
                    chars.update(chr(c) for c in range(97, 123))  # a-z
                    chars.update(str(i) for i in range(10))  # 0-9
                    chars.add('_')
                elif item[1] == sre_constants.CATEGORY_NOT_DIGIT:  # /D
                    # All printable ASCII except digits
                    chars.update(chr(c) for c in range(32, 127) if not chr(c).isdigit())
                elif item[1] == sre_constants.CATEGORY_NOT_WORD:  # /W
                    # All printable ASCII except word characters
                    chars.update(chr(c) for c in range(32, 127) if not (chr(c).isalnum() or chr(c) == '_'))
                elif item[1] == sre_constants.CATEGORY_SPACE:  # \s
                    chars.update(chr(c) for c in range(32, 127) if chr(c).isspace())
                elif item[1] == sre_constants.CATEGORY_NOT_SPACE:  # \S
                    # All printable ASCII except whitespace
                    chars.update(chr(c) for c in range(32, 127) if not chr(c).isspace())
                
                # Add more categories as needed
        for c in chars:
            rules.append((start, [c, end]))
            
    elif opcode == sre_constants.ANY:
        for c in map(chr, range(32, 127)):  # Printable ASCII only
            rules.append((start, [c, end]))

                
    elif opcode == sre_constants.AT:
        # Handle position anchors (^, $, \b, \B)
        # print("Handling AT:", arg)
        if arg == sre_constants.AT_BEGINNING:
            rules.append((start, [end]))  # ^ - matches only at start
        elif arg == sre_constants.AT_END:
            rules.append((start, [end]))  # $ - matches only at end
        else:
            # For word boundaries, handle \b and \B individually
            if arg == sre_constants.AT_BOUNDARY:  # \b
            # Word boundary: just match empty string
                rules.append((start, [end]))
            elif arg == sre_constants.AT_NON_BOUNDARY:  # \B
            # Non-word boundary: just match empty string
                rules.append((start, [end]))
            else:
            # Other AT positions: just match empty string
                rules.append((start, [end]))
            
    elif opcode == sre_constants.NOT_LITERAL:
        # Handle negative character class [^...]
        char = chr(arg)
        for c in map(chr, range(32, 127)):  # Printable ASCII
            if c != char:
                rules.append((start, [c, end]))
                
    elif opcode == sre_constants.CATEGORY:
        #print("Handling category:", arg)
         # Handle character categories like \d, \w, \s, etc.
        chars = set()
        if arg == sre_constants.CATEGORY_DIGIT:
            chars.update(str(i) for i in range(10))
            rules.append((start, [end]))  # \d - matches any digit
        elif arg == sre_constants.CATEGORY_WORD:
            chars.update(chr(c) for c in range(65, 91))  # A-Z
            chars.update(chr(c) for c in range(97, 123))  # a-z
            chars.update(str(i) for i in range(10))  # 0-9
            chars.add('_')
            rules.append((start, [end]))  # \w - matches any word character
        elif arg == sre_constants.CATEGORY_NOT_DIGIT:  # /D
            # All printable ASCII except digits
            chars.update(chr(c) for c in range(32, 127) if not chr(c).isdigit())
            rules.append((start, [end]))
        elif arg == sre_constants.CATEGORY_NOT_WORD:  # /W
            # All printable ASCII except word characters
            chars.update(chr(c) for c in range(32, 127) if not (chr(c).isalnum() or chr(c) == '_'))
            rules.append((start, [end]))
        elif arg == sre_constants.CATEGORY_SPACE:  # \s
            chars.update(chr(c) for c in range(32, 127) if chr(c).isspace())
            rules.append((start, [end]))
        elif arg == sre_constants.CATEGORY_NOT_SPACE:  # \S
            # All printable ASCII except whitespace
            chars.update(chr(c) for c in range(32, 127) if not chr(c).isspace())
            rules.append((start, [end]))
        # Add more categories as needed
        for c in chars:
            rules.append((start, [c, end]))
    
    elif opcode == sre_constants.ASSERT:
        # Lookahead assertion - just match the pattern without consuming input
        lookahead_start, lookahead_end, lookahead_rules = convert_parsed(arg[1], base_nt, counter, non_terminals)
        rules.extend(lookahead_rules)
        rules.append((start, [lookahead_start, end]))
        rules.append((lookahead_end, []))
        
    elif opcode == sre_constants.ASSERT_NOT:
        # Negative lookahead - not directly representable in EBNF
        # Add a comment or placeholder rule to indicate unsupported feature
        #print("Warning: Negative lookahead (ASSERT_NOT) is not supported in EBNF, using placeholder.")
        # Just match empty string as a placeholder
        rules.append((start, [end]))
        
    else:
        # For unsupported features, create a placeholder rule
        #print("Unsupported feature encountered with placeholder rule...")
        rules.append((start, [end]))
        
    return start, end, rules

def convert_parsed(parsed, base_nt, counter, non_terminals):
    """Convert parsed regex (list of tokens) to EBNF rules."""
    if not parsed:
        start = end = new_non_terminal(base_nt, counter)
        non_terminals.add(start)
        return start, end, [(start, [])]
        
    start = new_non_terminal(base_nt, counter)
    current = start
    rules = []
    non_terminals.add(start)

    skip_next = False
    for idx, token in enumerate(parsed):
        if skip_next:
            skip_next = False
            continue
        else:
            #print("TOKEN: ", token[0], token[1])
            # If this is a MAX_REPEAT or MIN_REPEAT and the next token is a duplicate literal, skip the next
            if token[0] in (sre_constants.MAX_REPEAT, sre_constants.MIN_REPEAT, sre_constants.REPEAT):
                #print("REPEAT: ", token)
                min_cnt, max_cnt, item = token[1]
                # If item is a list with one LITERAL and next token is same LITERAL, skip next
                if isinstance(item, list) and len(item) == 1 and item[0][0] == sre_constants.LITERAL:
                    if idx + 1 < len(parsed) and parsed[idx + 1][0] == sre_constants.LITERAL and parsed[idx + 1][1] == item[0][1]:
                        skip_next = True
            t_start, t_end, t_rules = convert_token(token, base_nt, counter, non_terminals)
            rules.append((current, [t_start]))
            rules.extend(t_rules)
            current = t_end
            non_terminals.add(current)
        
    return start, current, rules
def format_rule(lhs, alternatives, non_terminals):
    """Format an EBNF rule from its left-hand side and alternatives."""
    alt_strs = []
    for alt in alternatives:
        sym_strs = []
        for sym in alt:
            if sym in non_terminals:
                sym_strs.append(sym)
            else:  # Terminal (single character)
                sym_strs.append(f"'{escape_char(sym)}'")
        alt_strs.append(' '.join(sym_strs) if sym_strs else '')
    return f"{lhs} ::= {' | '.join(alt_strs)}"

def regex_to_ebnf(regex, start_symbol="start", base_nt="A"):
    """Convert a regex pattern to an EBNF grammar string."""
    try:
        # Preprocess regex to handle some special cases
        regex = regex.strip('/')  # Remove leading/trailing slashes if present
        
        # Handle some common regex features that sre_parse might not handle well
        regex = re.sub(r'\\([0-9])', r'\1', regex)  # Handle backreferences
        #print("Preprocessed Regex: ",regex)
        #regex = re.sub(r'\\[a-zA-Z]', lambda m: m.group(0).upper(), regex)  # Make letter escapes uppercase
        # Remove meaningless backslashes (not followed by a valid escape)
        # Valid escapes: d D w W s S b B t r n f 0 x u U {digits}
        regex = re.sub(
            r'\\(?![dDwWsSbBtTrRnRf0xuU]|u\{[0-9A-Fa-f]+\}|[1-9])',
            '',
            regex
        )
        
        # Handle "||" (empty alternative) by replacing with "|\"\"|"
        regex = re.sub(r'\|\|', '|""|', regex)

        # Handle "|" at the beginning or end of the regex
        if regex.startswith('|'):
            regex = '""|' + regex[1:]
        if regex.endswith('|'):
            regex = regex + '|""'
        
        #print("Regex Tokens: ",regex)
        parsed = sre_parse.parse(regex)

        #print("Parsed Tokens: ",list(parsed))
    except Exception as e:
        raise ValueError(f"Invalid regex: {e}") from e
        
    counter = [0]
    non_terminals = set()
    start_nt, end_nt, rules = convert_parsed(parsed, base_nt, counter, non_terminals)
    
    rules.append((start_symbol, [start_nt]))
    
    
     # Define non-terminals for letters, digits, and special characters
    letters_nt = "LETTERS"
    digits_nt = "DIGITS"
    specials_nt = "SPECIALS"
    epsilon_nt = "EPSILON"
    non_terminals.update([letters_nt, digits_nt, specials_nt, epsilon_nt])

    # Letters: a-zA-Z
    #for c in [chr(i) for i in range(ord('a'), ord('z')+1)] + [chr(i) for i in range(ord('A'), ord('Z')+1)]:
    #    rules.append((letters_nt, [c]))
    # Digits: 0-9
    #for c in [chr(i) for i in range(ord('0'), ord('9')+1)]:
    #    rules.append((digits_nt, [c]))
    # Specials: printable ASCII except letters and digits
    #for c in [chr(i) for i in range(32, 127) if not chr(i).isalnum()]:
    #    rules.append((specials_nt, [c]))
   
    
    # end_nt can be any of these
    #rules.append((end_nt, [letters_nt]))
    #rules.append((end_nt, [digits_nt]))
    #rules.append((end_nt, [specials_nt]))
    rules.append((epsilon_nt, ['']))  # Adding epsilon explicitly
    rules.append((end_nt, [epsilon_nt]))

    #print(f"Start non-terminal: {start_nt}, start <{start_symbol}>, End non-terminal: {end_nt}")
    non_terminals.update([start_symbol, end_nt])
    
    # Group rules by left-hand side
    grouped = {}
    for lhs, rhs in rules:
        grouped.setdefault(lhs, []).append(rhs)
        
    # Format rules ensuring start_symbol is first
    ebnf = [format_rule(start_symbol, grouped[start_symbol], non_terminals)]
    for lhs in grouped:
        if lhs != start_symbol:
            ebnf.append(format_rule(lhs, grouped[lhs], non_terminals))
            
    return '\n'.join(ebnf)
def wrap_nt(nt):
    return f"<{nt}>"

def wrap_rules(ebnf_str):
    """Wrap all non-terminals in angle brackets in the EBNF grammar string."""
    # Find all non-terminals (identifiers on the left of ::=)
    nts = set(re.findall(r'^(\w+)\s*::=', ebnf_str, re.MULTILINE))
    # Sort by length descending to avoid partial replacements (e.g., A1 before A10)
    nts_sorted = sorted(nts, key=lambda x: -len(x))
    for nt in nts_sorted:
        ebnf_str = re.sub(rf'\b{re.escape(nt)}\b', f"<{nt}>", ebnf_str)
    # Remove extra single quotes around repeated literals like ''t'{4}' -> 't'{4}
    ebnf_str = re.sub(r"''([a-zA-Z0-9])'\{(\d+(?:,\d*)?)\}'", r"'\1'{\2}", ebnf_str)
    # Replace ''<A5>'{4,8}' with <A5>{4,8}
    ebnf_str = re.sub(r"''(<\w+>)'\{(\d+(?:,\d*)?)\}'", r"\1{\2}", ebnf_str)
    return ebnf_str

def inline_non_terminals(ebnf_str):
    """Inline non-terminals that are used only once and are not recursive."""
    import re
    # Parse rules
    rule_pattern = re.compile(r'^<(\w+)>\s*::=\s*(.*)$', re.MULTILINE)
    rules = {m.group(1): m.group(2) for m in rule_pattern.finditer(ebnf_str)}
    # Count non-terminal usages
    usage = {nt: 0 for nt in rules}
    for rhs in rules.values():
        for nt in rules:
            usage[nt] += len(re.findall(rf'<{nt}>', rhs))
    # Inline non-terminals used only once and not recursive
    changed = True
    while changed:
        changed = False
        for nt, count in list(usage.items()):
            if count == 1 and nt != "start":
                rhs = rules[nt]
                # Avoid inlining recursive rules
                if f'<{nt}>' not in rhs:
                    # Find the rule that uses this nt
                    for parent, parent_rhs in rules.items():
                        if f'<{nt}>' in parent_rhs:
                            # Inline
                            rules[parent] = parent_rhs.replace(f'<{nt}>', f'({rhs})')
                            del rules[nt]
                            del usage[nt]
                            changed = True
                            break
                if changed:
                    break
    # Rebuild EBNF string
    ebnf_lines = [f"<{nt}> ::= {rhs}" for nt, rhs in rules.items()]
    return '\n'.join(ebnf_lines)

def generate_ebnf_from_regex(regex):
    """Generate EBNF grammar from a regex pattern."""
    ebnf_grammar = regex_to_ebnf(regex)
    ebnf_grammar = wrap_rules(ebnf_grammar)
    #ebnf_grammar = inline_non_terminals(ebnf_grammar)
    with open("test.fan", "w") as f:
        f.write(ebnf_grammar)
    return ebnf_grammar

if __name__ == "__main__":

    # Different modes.
    # 1. regex supplied in a .txt file
    # 2. regex supplied as a command line argument
    import argparse
    import sys

    # Create argument parser
    parser = argparse.ArgumentParser(description="Convert a regex pattern to EBNF grammar.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-f", "--file", type=str, help="Path to a file containing the regex pattern.")
    group.add_argument("-r", "--regex", type=str, help="Raw regex pattern as a string.")
    parser.add_argument("-w", "--write", action="store_true", help="Write the EBNF grammar to test.fan")

    # Parse arguments
    args = parser.parse_args()

    # Read regex from file or use raw regex
    if args.file:
        try:
            with open(args.file, "r") as file:
                regex = file.read().strip()
        except FileNotFoundError:
            print(f"Error: File '{args.file}' not found.", file=sys.stderr)
            sys.exit(1)
    elif args.regex:
        regex = args.regex.strip()
    else:
        print("Incorrect usage. See:")
        parser.print_help()
        sys.exit(1)

    ebnf_grammar = generate_ebnf_from_regex(regex)
    print("Regex supplied:", regex)
    print("EBNF Grammar:")
    print(ebnf_grammar)

    if args.write:
        with open("test.fan", "w") as f:
            f.write(ebnf_grammar)

__all__ = [
    "regex_to_ebnf",
    "wrap_nt",
    "wrap_rules",
    "generate_ebnf_from_regex"
]