import sre_parse

class RegexToEBNF:
    def __init__(self):
        self.rules = []
        self.group_counter = 1

    def convert(self, regex):
        parsed = sre_parse.parse(regex)
        start_rule = self._handle_subpattern(parsed)
        ebnf = []
        ebnf.append(f"<start> ::= {start_rule}")
        ebnf.extend(self.rules)
        return "\n\n".join(ebnf)

    def _handle_subpattern(self, pattern):
        parts = []
        for token, value in pattern:
            if token == "literal":
                parts.append(f"\"{chr(value)}\"")

            elif token == "in":  # character class
                if all(t[0] == "category" and t[1] == "category_digit" for t in value):
                    parts.append("<digit>")
                    self._add_digit_rule()
                else:
                    parts.append(self._handle_charclass(value))

            elif token == "subpattern":
                rule_name = f"<group{self.group_counter}>"
                self.group_counter += 1
                sub = self._handle_subpattern(value[1])
                self.rules.append(f"{rule_name} ::= {sub}")
                parts.append(rule_name)

            elif token == "branch":  # alternation
                branches = []
                for branch in value[1]:
                    branches.append(self._handle_subpattern(branch))
                parts.append("( " + " | ".join(branches) + " )")

            elif token == "max_repeat":
                min_rep, max_rep, subp = value
                inner = self._handle_subpattern(subp)
                if min_rep == 0 and max_rep == sre_parse.MAXREPEAT:
                    parts.append(f"{{ {inner} }}")
                elif min_rep == 1 and max_rep == sre_parse.MAXREPEAT:
                    parts.append(f"{inner} , {{ {inner} }}")
                elif min_rep == 0 and max_rep == 1:
                    parts.append(f"[ {inner} ]")
                else:
                    parts.append(f"{{ {inner} }}  (* {min_rep}..{max_rep} times *)")

            elif token == "category" and value == "category_digit":
                parts.append("<digit>")
                self._add_digit_rule()

            else:
                parts.append(f"/* unhandled: {token} {value} */")
        return " , ".join(parts)

    def _handle_charclass(self, items):
        chars = []
        for t, v in items:
            if t == "literal":
                chars.append(f"\"{chr(v)}\"")
        return "( " + " | ".join(chars) + " )"

    def _add_digit_rule(self):
        digit_rule = "<digit> ::= " + " | ".join(f"\"{i}\"" for i in range(10))
        if digit_rule not in self.rules:
            self.rules.append(digit_rule)


if __name__ == "__main__":
    regex = r"ab(c|de)*f\d+"
    converter = RegexToEBNF()
    print(converter.convert(regex))

