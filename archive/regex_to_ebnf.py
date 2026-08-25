import sre_parse
import sre_constants
import re

def new_non_terminal(base_nt, counter):
    """Generate a new unique non-terminal symbol."""
    name = f"{base_nt}{counter[0]}"
    counter[0] += 1
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
    
    if opcode == sre_constants.LITERAL:
        char = chr(arg)
        rules.append((start, [char, end]))
        
    elif opcode == sre_constants.IN:
        chars = set()
        for item in arg:
            if item[0] == sre_constants.LITERAL:
                chars.add(chr(item[1]))
            elif item[0] == sre_constants.RANGE:
                low, high = item[1]
                chars.update(chr(c) for c in range(low, high + 1))
        for c in chars:
            rules.append((start, [c, end]))
            
    elif opcode == sre_constants.ANY:
        for c in map(chr, range(0, 256)):
            rules.append((start, [c, end]))
            
    elif opcode in (sre_constants.BRANCH, sre_constants.SUBPATTERN):
        branches = arg[1] if opcode == sre_constants.BRANCH else [arg[3]]
        for branch in branches:
            b_start, b_end, b_rules = convert_parsed(branch, base_nt, counter, non_terminals)
            rules.append((start, [b_start]))
            rules.append((b_end, [end]))
            rules.extend(b_rules)
            
    elif opcode in (sre_constants.REPEAT, sre_constants.MIN_REPEAT, sre_constants.MAX_REPEAT):
        min_cnt, max_cnt, item = arg
        exp_start, exp_end, exp_rules = convert_parsed(item, base_nt, counter, non_terminals)
        rules.extend(exp_rules)
        
        if min_cnt == 0 and max_cnt == sre_constants.MAXREPEAT:  # *
            rules.extend([(start, [end]), (start, [exp_start]), 
                         (exp_end, [start]), (exp_end, [end])])
        elif min_cnt == 1 and max_cnt == sre_constants.MAXREPEAT:  # +
            rules.extend([(start, [exp_start]), (exp_end, [start]), (exp_end, [end])])
        elif min_cnt == 0 and max_cnt == 1:  # ?
            rules.extend([(start, [end]), (start, [exp_start]), (exp_end, [end])])
        else:
            raise NotImplementedError(f"Unsupported repeat: {{{min_cnt},{max_cnt}}}")
            
    else:
        raise NotImplementedError(f"Unsupported opcode: {opcode}")
        
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
    
    for token in parsed:
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
        alt_strs.append(' '.join(sym_strs))
    return f"{lhs} ::= {' | '.join(alt_strs)}"

def regex_to_ebnf(regex, start_symbol="start", base_nt="A"):
    """Convert a regex pattern to an EBNF grammar string."""
    try:
        parsed = sre_parse.parse(regex)
    except Exception as e:
        raise ValueError(f"Invalid regex: {e}") from e
        
    counter = [0]
    non_terminals = set()
    
#add start and end non-terminals 
# TODO: add <> tag for each rule 


# After parsing, wrap all non-terminals in rules and update non_terminals set
# (This will be done after rules are generated, before formatting)

    start_nt, end_nt, rules = convert_parsed(parsed, base_nt, counter, non_terminals)
    
    rules.append((start_symbol, [start_nt]))

    # Define non-terminals for letters, digits, and special characters
    letters_nt = "LETTERS"
    digits_nt = "DIGITS"
    specials_nt = "SPECIALS"
    epsilon_nt = "EPSILON"
    non_terminals.update([letters_nt, digits_nt, specials_nt, epsilon_nt])

    # Letters: a-zA-Z
    for c in [chr(i) for i in range(ord('a'), ord('z')+1)] + [chr(i) for i in range(ord('A'), ord('Z')+1)]:
        rules.append((letters_nt, [c]))
    # Digits: 0-9
    for c in [chr(i) for i in range(ord('0'), ord('9')+1)]:
        rules.append((digits_nt, [c]))
    # Specials: printable ASCII except letters and digits
    for c in [chr(i) for i in range(32, 127) if not chr(i).isalnum()]:
        rules.append((specials_nt, [c]))
    rules.append((epsilon_nt, ['']))  # Adding epsilon explicitly

    # end_nt can be any of these
    rules.append((end_nt, [letters_nt]))
    rules.append((end_nt, [digits_nt]))
    rules.append((end_nt, [specials_nt]))
    rules.append((end_nt, [epsilon_nt]))
    print(f"Start non-terminal: {start_nt}, start <{start_symbol}>, End non-terminal: {end_nt}")
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
    return ebnf_str

def generate_ebnf_from_regex(regex):
    """Generate EBNF grammar from a regex pattern."""
    ebnf_grammar = regex_to_ebnf(regex)
    ebnf_grammar = wrap_rules(ebnf_grammar)
    return ebnf_grammar

if __name__ == "__main__":
    regex = "/.|c?yhFj^/" #"a(b|c)*d?"
    ebnf_grammar = generate_ebnf_from_regex(regex)
    print("EBNF Grammar:")
    print(ebnf_grammar)

    with open("ebnf_grammar.txt", "w") as f:
        f.write(ebnf_grammar)

__all__ = [
    "regex_to_ebnf",
    "wrap_nt",
    "wrap_rules",
]