import sre_parse
import sys
import string

# Basic expansions for shorthand escapes
ESCAPE_MAP = {
    r"\d": " | ".join(f'"{d}"' for d in "0123456789"),
    r"\w": " | ".join(f'"{c}"' for c in string.ascii_letters + string.digits + "_"),
    r"\s": '" " | "\\t" | "\\n" | "\\r" | "\\f" | "\\v"'
}

def token_to_ebnf(token):
    t_type, t_value = token

    if t_type == "literal":
        return f'"{chr(t_value)}"'
    elif t_type == "in":
        # character class
        parts = []
        for inner in t_value:
            if inner[0] == "literal":
                parts.append(f'"{chr(inner[1])}"')
            elif inner[0] == "range":
                start, end = inner[1]
                parts.extend(f'"{chr(c)}"' for c in range(start, end + 1))
        return " | ".join(parts)
    elif t_type == "any":
        return "<any_character>"
    elif t_type == "max_repeat":
        min_r, max_r, subpattern = t_value
        inner = sequence_to_ebnf(subpattern)
        if min_r == 0 and max_r == 1:
            return f"[ {inner} ]"
        elif min_r == 0 and max_r == sre_parse.MAXREPEAT:
            return f"{{ {inner} }}"
        elif min_r == 1 and max_r == sre_parse.MAXREPEAT:
            return f"{inner} , {{ {inner} }}"
        else:
            fixed = ", ".join([inner] * min_r)
            if max_r == sre_parse.MAXREPEAT:
                return f"{fixed} , {{ {inner} }}"
            else:
                extra = ", ".join([inner] * (max_r - min_r))
                return f"[ {extra} ]" if extra else fixed
    elif t_type == "branch":
        _, branches = t_value
        return " | ".join(sequence_to_ebnf(branch) for branch in branches)
    elif t_type == "subpattern":
        return sequence_to_ebnf(t_value[1])
    elif t_type == "category":
        cat = str(t_value)
        if cat.endswith("CATEGORY_DIGIT"):
            return ESCAPE_MAP[r"\d"]
        elif cat.endswith("CATEGORY_WORD"):
            return ESCAPE_MAP[r"\w"]
        elif cat.endswith("CATEGORY_SPACE"):
            return ESCAPE_MAP[r"\s"]
        else:
            return "<unknown_category>"
    else:
        return f"<unhandled:{t_type}>"

def sequence_to_ebnf(seq):
    parts = []
    for token in seq:
        parts.append(token_to_ebnf(token))
    return " , ".join(parts) if parts else '""'

def regex_to_ebnf(regex):
    parsed = sre_parse.parse(regex)
    return f"<start> ::= {sequence_to_ebnf(parsed)}"

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python regex2ebnf.py '<regex>'")
        sys.exit(1)

    regex = sys.argv[1]
    ebnf = regex_to_ebnf(regex)
    print(ebnf)

