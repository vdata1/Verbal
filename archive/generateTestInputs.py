import sre_parse
import string

def regex_to_fandango_grammar(regex, start_rule="<start>"):
    parsed = sre_parse.parse(regex)
    rules = []
    group_count = 0

    def parse_tokens(tokens):
        nonlocal group_count
        parts = []
        for tok in tokens:
            t_type, t_val = tok
            if t_type == sre_parse.LITERAL:
                parts.append(f'"{chr(t_val)}"')
            elif t_type == sre_parse.SUBPATTERN:
                group_count += 1
                group_name = f"<group{group_count}>"
                sub_tokens = t_val[1]
                sub_expr = parse_tokens(sub_tokens)
                rules.append(f"{group_name} ::= {sub_expr}")
                parts.append(f"{group_name}")
            elif t_type == sre_parse.BRANCH:
                # t_val = (None, [list of alternatives])
                alts = [parse_tokens(alt) for alt in t_val[1]]
                parts.append(" | ".join(alts))
            elif t_type == sre_parse.MAX_REPEAT:
                min_r, max_r, sub_tokens = t_val
                sub_expr = parse_tokens(sub_tokens)
                if min_r == 0 and max_r is None:
                    parts.append(f"{{ {sub_expr} }}")   # *
                elif min_r == 1 and max_r is None:
                    parts.append(f"{sub_expr} , {{ {sub_expr} }}")  # +
                elif min_r == 0 and max_r == 1:
                    parts.append(f"[ {sub_expr} ]")  # ?
                else:
                    parts.append(f"{sub_expr}{{{min_r},{'' if max_r is None else max_r}}}")
            elif t_type == sre_parse.IN:
                # character class
                chars = []
                for in_tok in t_val:
                    itype, ival = in_tok
                    if itype == sre_parse.LITERAL:
                        chars.append(f'"{chr(ival)}"')
                    elif itype == sre_parse.RANGE:
                        start, end = ival
                        chars.extend([f'"{chr(c)}"' for c in range(start, end+1)])
                parts.append(" | ".join(chars))
            elif t_type == sre_parse.CATEGORY:
                cat_map = {
                    sre_parse.CATEGORY_DIGIT: "<digit>",
                    sre_parse.CATEGORY_WORD: "<wordchar>",
                    sre_parse.CATEGORY_SPACE: "<space>",
                }
                parts.append(cat_map.get(t_val, f"<cat_{t_val}>"))
            else:
                # fallback
                parts.append(f"<{t_type}>")
        return " , ".join(parts)

    start_expr = parse_tokens(parsed)
    rules = [f"{start_rule} ::= {start_expr}"] + rules

    # Add basic predefined rules
    rules += [
        "<digit> ::= " + " | ".join(f'"{d}"' for d in string.digits),
        "<wordchar> ::= " + " | ".join(f'"{c}"' for c in string.ascii_letters + string.digits + "_"),
        "<space> ::= " + " | ".join(repr(c) for c in [" ", "\t", "\n", "\r"])
    ]

    return "\n".join(rules)


if __name__ == "__main__":
    regex = r"ab(c|de)*f\d+"
    grammar = regex_to_fandango_grammar(regex)
    print(grammar)
