from grammar_utils.regex import Regex

r = Regex(r"^\b.{58}\b")
g = r.to_grammar()
print(g)

