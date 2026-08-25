<Pattern> ::= <Disjunction>

<Disjunction> ::= <Alternative> ( "|" <Alternative> )*

<Alternative> ::= <Term>*

<Term> ::= <Assertion>
         | <Atom> <Quantifier>?

<Assertion> ::= "^"              (* Start of input *)
              | "$"              (* End of input *)
              | "\b"             (* Word boundary *)
              | "\B"             (* Non-word boundary *)
              | "(?=" <Disjunction> ")"  (* Positive Lookahead *)
              | "(?!" <Disjunction> ")"  (* Negative Lookahead *)

<Atom> ::= <PatternCharacter>
         | <BackslashSequence>
         | <CharacterClass>
         | <ParenthesizedGroup>
         | "."              (* Any character except newline *)

<PatternCharacter> ::= (* Any character that is not a special regex character: ^ $ \ . * + ? ( ) [ ] { } | *)

<BackslashSequence> ::= "\d" | "\D" (* Digit/Non-digit *)
                      | "\w" | "\W" (* Word character/Non-word character *)
                      | "\s" | "\S" (* Whitespace/Non-whitespace *)
                      | "\t" | "\n" | "\r" | "\f" | "\v" (* Tab, Newline, etc. *)
                      | "\x" <HexDigit> <HexDigit> (* Hex escape *)
                      | "\u" <HexDigit> <HexDigit> <HexDigit> <HexDigit> (* Unicode escape *)
                      | "\u{" <HexDigit>+ "}" (* Unicode code point escape *)
                      | "\" <DecimalDigit>+ (* Backreference *)
                      | "\" <ControlLetter> (* Control escape *)
                      | "\" <PatternCharacter> (* Escaped special character *)

<CharacterClass> ::= "[" <ClassRanges> "]" (* Positive character class *)
                   | "[^" <ClassRanges> "]" (* Negative character class *)

<ClassRanges> ::= <ClassAtom>*
                | <ClassAtom> "-" <ClassAtom> <ClassRanges> (* Range *)

<ClassAtom> ::= <PatternCharacter> | <BackslashSequence> | <CharacterClassEscape>

<CharacterClassEscape> ::= "\d" | "\D" | "\w" | "\W" | "\s" | "\S"

<ParenthesizedGroup> ::= "(" <Disjunction> ")"          (* Capturing group *)
                       | "(?:" <Disjunction> ")"         (* Non-capturing group *)
                       | "(?<" <GroupName> ">" <Disjunction> ")" (* Named capturing group *)

<GroupName> ::= (* A valid JavaScript identifier *)

<Quantifier> ::= "*"
               | "+"
               | "?"
               | "{" <DecimalDigit>+ "}"
               | "{" <DecimalDigit>+ "," "}"
               | "{" <DecimalDigit>+ "," <DecimalDigit>+ "}"
               | <Quantifier> "?" (* Non-greedy quantifier *)

<HexDigit> ::= [0-9a-fA-F]
<DecimalDigit> ::= [0-9]
<ControlLetter> ::= [a-zA-Z]

