import re
import sre_parse
import sre_constants
from typing import List, Any, Optional, Dict
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
MAX_UNICODE = 0x10FFFF


def rewrite_js_codepoint_escapes(pattern: str) -> str:
    r"""Rewrite braced code-point escapes ``\u{HEX}`` and ``\x{HEX}`` into a form
    Python's ``sre_parse`` accepts.

    Python understands ``\uHHHH`` (exactly four hex) and ``\U00HHHHHH`` (exactly
    eight hex) but NOT the braced forms ``\u{...}`` / ``\x{...}`` -- ``sre_parse``
    aborts with "incomplete escape \u" / "incomplete escape \x". Corpus patterns
    that use ``\u{1D306}`` (or ``[\u{11EE0}-\u{11EF8}]`` as a range endpoint), and
    Perl/PCRE-style ``\x{e1}`` (= U+00E1), therefore never compile. We translate each
    such escape to ``\U`` + eight-digit zero-padded hex so the code point survives
    into the grammar as a literal; both standalone and in-class range positions
    accept ``\U########`` identically.

    Both braced forms are read as THE CODE POINT -- a deliberate modeling choice.
    For ``\u{1D306}`` this is exactly ES6 (``u``-flag) semantics. ``\x{...}`` is
    Perl/PCRE, not literal JS: JS spells a hex escape ``\xHH`` (exactly two hex) and
    has no braced ``\x{...}`` form (Annex-B non-``u`` reads ``\x{e1}`` as the letters
    ``x{e1}``; the ``u`` flag rejects it outright). A corpus author writing
    ``\x{e1}`` plainly meant the code point U+00E1, so we adopt the code-point
    reading to MATCH the ``\u{}`` decision -- highest fidelity for differential
    testing (all engines then interpret the emitted ``\U########`` identically).
    This reading is worth a sentence in the paper.

    Only genuine braced escapes with all-hex, in-range contents are rewritten;
    ``\\u{...}`` / ``\\x{...}`` (escaped backslash), non-hex contents, and
    out-of-range values are left untouched so they parse (or fail) exactly as before.

    Raises ``ValueError`` on a code point above U+10FFFF (invalid everywhere).
    """
    out: List[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        # An unescaped backslash. Is it the start of `\u{...}` or `\x{...}`?
        if pattern.startswith("u{", i + 1) or pattern.startswith("x{", i + 1):
            kind = pattern[i + 1]  # 'u' or 'x', for the diagnostic
            close = pattern.find("}", i + 3)
            if close != -1:
                hexdigits = pattern[i + 3:close]
                if hexdigits and all(ch in _HEX_DIGITS for ch in hexdigits):
                    cp = int(hexdigits, 16)
                    if cp > MAX_UNICODE:
                        raise ValueError(
                            f"code point U+{cp:X} in \\{kind}{{{hexdigits}}} exceeds "
                            f"U+{MAX_UNICODE:X}"
                        )
                    out.append(f"\\U{cp:08X}")
                    i = close + 1
                    continue
        # Not a braced code-point escape: copy the backslash AND the escaped char
        # verbatim so the following char is never misread as a fresh escape.
        out.append(c)
        if i + 1 < n:
            out.append(pattern[i + 1])
            i += 2
        else:
            i += 1
    return "".join(out)


# Letters JS reads as identity escapes (the bare letter) where Perl and Python read
# something else, so `sre_parse` diverges from every JS engine:
#   \A -> "A", \Z -> "Z"                      (Python: string anchors)
#   \z, \Q, \E, \G, \e, \K -> the letter    (Python: rejected as "bad escape")
# In JS outside `u` mode each is just the letter: `\Q..\E` is not Perl quoting, `/\e/`
# matches "e" rather than ESC, and JS has no Perl `\K`. Since every target engine is
# JS, the literal reading is the faithful one; modeling `\e` as ESC would generate ESC
# where the real regex wants "e", a spurious discrepancy. These are SyntaxErrors under
# `u`, which harnesses adding `u` capture as a comparable {ok:false,error}.
#
# Only letters where JS disagrees with Python are listed; the ones they agree on
# (\b \B \d \D \s \S \w \W \n \r \t \f \v) are left to `sre_parse`. Control escapes
# `\cX` map to a different character, not the letter, and are handled by
# `rewrite_js_control_escapes`.
_JS_IDENTITY_LETTER_ESCAPES = frozenset("AZzQEGeK")


def rewrite_js_identity_escapes(pattern: str) -> str:
    r"""Rewrite JS identity escapes (``\A \Z \z \Q \E \G``) to their literal letters.

    Backslash-run aware: ``\\A`` is an escaped backslash followed by ``A`` and is
    left untouched. Applied before ``sre_parse`` so Python parses the letter, and
    applied identically to the neutral oracle / pad selection so the grammar, the
    engine, and the oracle all read the same pattern.
    """
    out: List[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        nxt = pattern[i + 1] if i + 1 < n else ""
        if nxt in _JS_IDENTITY_LETTER_ESCAPES:
            out.append(nxt)  # drop the backslash -> literal letter (JS identity escape)
            i += 2
            continue
        # Some other escape: copy the backslash AND the escaped char verbatim so the
        # next char is never misread as a fresh escape.
        out.append(c)
        if i + 1 < n:
            out.append(pattern[i + 1])
            i += 2
        else:
            i += 1
    return "".join(out)


_ASCII_LETTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)


_SAFE_CHAR_REPLACEMENTS = {
    '\\': '\\\\',
    '"': '\\"',
    "'": "\\'",
    '`': '\\`',
    '\n': '\\n',
    '\r': '\\r',
    '\t': '\\t',
}


def _safe_char_replace(char: str) -> str:
    r"""Escape one character for safe emission into a Fandango terminal (both the
    ``"..."`` literal and the ``r'[...]'`` char-class contexts accept the results).

    Beyond the metacharacter/quote/whitespace map, RAW C0 control bytes (0x00-0x1F),
    DEL (0x7F), and high Latin-1 bytes (0x80-0xFF) must NOT reach the grammar text:
    a NUL terminates it, a raw newline/form-feed splits a rule across lines, and
    high bytes trip the parser's encoding -- the FandangoSyntaxError /
    "unterminated string literal" family (regex_135, 1426, 2048, 932, ...). We emit
    those as ``\xHH`` (a two-hex escape valid in both contexts). Printable ASCII and
    BMP/astral characters (>= U+0100, e.g. the literal a ``\u{...}`` / ``\x{...}``
    escape lowered to) pass through unchanged, preserving those raw-literal rewrites.
    """
    if char in _SAFE_CHAR_REPLACEMENTS:
        return _SAFE_CHAR_REPLACEMENTS[char]
    o = ord(char)
    if o < 0x20 or 0x7F <= o <= 0xFF:
        return f'\\x{o:02x}'
    # Unicode line/paragraph separators (>= U+0100) would split a grammar-text line
    # if emitted raw, corrupting the .fan the same way a bare newline does
    # (regex_1045 has both U+2028 and U+2029 in a char class ->
    #  FandangoSyntaxError). Escape those specifically; other BMP/astral
    #  chars still pass through raw -- exrex reads them fine and they do
    #  not break the grammar text -- preserving the \u{...} rewrites.
    if o in (0x2028, 0x2029):
        return f'\\u{o:04x}'
    return char


def rewrite_js_empty_class(pattern: str) -> str:
    r"""Rewrite JS empty character classes, which Python's ``sre_parse`` rejects.

    In JS an empty class is meaningful and the ``]`` closes it immediately:
    ``[]`` matches NOTHING and ``[^]`` matches ANY character (including line
    terminators -- the common "dot-all" idiom). Python instead reads the ``]`` as a
    literal member and scans on, so ``[^]*?x`` raises "unterminated character set"
    (regex_2368) and ``[]abc`` silently mis-parses. We rewrite only the empty forms
    at a class OPENER:

        ``[^]`` -> ``[\s\S]``                 (any character, incl. newline)
        ``[]``  -> ``[^\x00-\U0010FFFF]``     (matches nothing)

    Char-class and backslash-run aware: an inner ``[`` (``[([]``) or a ``]`` that is
    a member of a non-empty class is never mistaken for an empty class.
    """
    out: List[str] = []
    i, n = 0, len(pattern)
    in_class = False
    while i < n:
        c = pattern[i]
        if c == "\\":
            out.append(c)
            if i + 1 < n:
                out.append(pattern[i + 1])
                i += 2
            else:
                i += 1
            continue
        if not in_class and c == "[":
            if pattern[i + 1:i + 2] == "]":                       # `[]` -> nothing
                out.append("[^\\x00-\\U0010FFFF]")
                i += 2
                continue
            if pattern[i + 1:i + 3] == "^]":                      # `[^]` -> any char
                out.append("[\\s\\S]")
                i += 3
                continue
            in_class = True
            out.append(c)
            i += 1
            # A leading `]` (optionally after `^`) is a literal member (Python rule);
            # consume it so it does not close the class prematurely.
            if i < n and pattern[i] == "^":
                out.append("^")
                i += 1
            if i < n and pattern[i] == "]":
                out.append("]")
                i += 1
            continue
        if in_class and c == "]":
            in_class = False
        out.append(c)
        i += 1
    return "".join(out)


_CLASS_SHORTHAND_LETTERS = frozenset("dDsSwW")


def rewrite_js_class_shorthand_ranges(pattern: str) -> str:
    r"""Inside ``[...]``, escape a literal ``-`` that sits next to a shorthand class
    (``\d \D \s \S \w \W``).

    In JS such a ``-`` is a LITERAL member -- ``[\w-\.]`` is {word chars, ``-``,
    ``.``}, ``[\w-_]`` is {word chars, ``-``, ``_``} (verified on node) -- because a
    range needs single-character endpoints and a shorthand class is not one. Python's
    ``sre_parse`` instead reads it as a range endpoint and raises "bad character range
    \w-\.". We escape the ``-`` to ``\-`` so ``sre_parse`` sees the literal JS meaning.

    A ``-`` is rewritten only when its LEFT or RIGHT neighbour is a shorthand class --
    exactly the configurations ``sre_parse`` rejects, so a genuine range (``[a-z]``)
    is never touched and no currently-parsing regex changes meaning. Backslash-run
    and char-class aware.
    """
    out: List[str] = []
    i, n = 0, len(pattern)
    in_class = False
    prev_shorthand = False
    while i < n:
        c = pattern[i]
        if c == "\\":
            nxt = pattern[i + 1] if i + 1 < n else ""
            if in_class and nxt in _CLASS_SHORTHAND_LETTERS:
                out.append(c)
                out.append(nxt)
                i += 2
                prev_shorthand = True
                continue
            # Any other escape: copy the backslash AND the escaped char verbatim.
            out.append(c)
            if i + 1 < n:
                out.append(pattern[i + 1])
                i += 2
            else:
                i += 1
            prev_shorthand = False
            continue
        if not in_class:
            if c == "[":
                in_class = True
                prev_shorthand = False
                out.append(c)
                i += 1
                if i < n and pattern[i] == "^":
                    out.append("^")
                    i += 1
                if i < n and pattern[i] == "]":  # leading `]` is a literal member
                    out.append("]")
                    i += 1
                continue
            out.append(c)
            i += 1
            continue
        # Inside a char class.
        if c == "]":
            in_class = False
            prev_shorthand = False
            out.append(c)
            i += 1
            continue
        if c == "-":
            next_shorthand = (pattern[i + 1:i + 2] == "\\"
                              and pattern[i + 2:i + 3] in _CLASS_SHORTHAND_LETTERS)
            out.append("\\-" if (prev_shorthand or next_shorthand) else "-")
            i += 1
            prev_shorthand = False
            continue
        out.append(c)
        i += 1
        prev_shorthand = False
    return "".join(out)


def rewrite_js_control_escapes(pattern: str) -> str:
    r"""Rewrite JS control escapes ``\cX`` to the actual control character.

    In JS, ``\c`` followed by an ASCII letter is the control character whose code is
    ``ord(letter) & 0x1F`` -- ``\cM`` is CR (0x0D), ``\cJ`` is LF (0x0A), ``\ca`` and
    ``\cA`` are both 0x01 (verified across node + bun for every letter, both cases).
    This holds identically in and out of a char class. Python's ``sre_parse`` rejects
    ``\c`` outright ("bad escape \c"), so we translate to a ``\xHH`` escape that
    ``sre_parse`` and every engine read as that exact control byte.

    ``\c`` NOT followed by a letter (e.g. ``\c@``) is an Annex-B IdentityEscape: JS
    reads it as the LITERAL two chars backslash + ``c`` (so ``/\c@/`` matches the
    string ``\c@`` and ``[^\c@]`` excludes ``\``, ``c``, ``@`` -- verified). We emit
    ``\\c`` (escaped backslash + literal ``c``) and leave the following char in place.

    Under the ``u`` flag JS accepts ``\cLetter`` (control) but rejects ``\c@`` as a
    SyntaxError -- comparable {ok:false,error}, handled by the u-flag harness.

    Backslash-run aware: ``\\cM`` is an escaped backslash + literal ``cM``, untouched.
    """
    out: List[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if pattern[i + 1:i + 2] == "c":
            letter = pattern[i + 2] if i + 2 < n else ""
            if letter in _ASCII_LETTERS:
                out.append(f"\\x{ord(letter) & 0x1F:02X}")  # control char
                i += 3
                continue
            # `\c` + non-letter (or end): Annex-B literal backslash + "c".
            out.append("\\\\c")
            i += 2
            continue
        # Any other escape: copy the backslash AND the escaped char verbatim.
        out.append(c)
        if i + 1 < n:
            out.append(pattern[i + 1])
            i += 2
        else:
            i += 1
    return "".join(out)


def rewrite_js_named_groups(pattern: str) -> str:
    r"""Rewrite JS named groups/backreferences to the Python spellings ``sre_parse``
    accepts: ``(?<name>...)`` -> ``(?P<name>...)`` and ``\k<name>`` -> ``(?P=name)``.

    JS (ES2018) and Python express the SAME feature -- a named capture group and a
    named backreference -- with different syntax; Python's ``sre_parse`` rejects the
    JS spelling outright ("unknown extension ?<"). This is a pure spelling
    translation, NOT a modeling choice: a named group is assigned a group number by
    ``sre_parse`` exactly as an unnamed one, so the existing SUBPATTERN / GROUPREF
    codegen handles it unchanged.

    Careful about two look-alikes that must be left ALONE:

    * **Lookbehind** ``(?<=...)`` / ``(?<!...)`` -- only rewrite ``(?<`` when the
      char after ``?<`` is neither ``=`` nor ``!`` (i.e. a real group name).
    * **Char classes** -- ``(?<`` and ``\k<`` inside ``[...]`` are literal characters,
      never group syntax, so we track class depth and rewrite only OUTSIDE a class.

    Backslash-run aware: ``\k`` is only a named backreference when the backslash is
    unescaped (``\\k`` is an escaped backslash + literal ``k``). Applied before
    ``sre_parse`` and identically to grammar / neutral oracle / pad selection via
    ``normalize_js_regex``.
    """
    out: List[str] = []
    i, n = 0, len(pattern)
    in_class = False
    while i < n:
        c = pattern[i]
        if c == "\\":
            # An unescaped backslash: is it `\k<name>` (a JS named backreference)?
            if (not in_class and pattern.startswith("k<", i + 1)):
                close = pattern.find(">", i + 3)
                if close != -1:
                    name = pattern[i + 3:close]
                    if name:
                        out.append(f"(?P={name})")
                        i = close + 1
                        continue
            # Any other escape: copy the backslash AND the escaped char verbatim so
            # the next char is never misread as a fresh escape (or class delimiter).
            out.append(c)
            if i + 1 < n:
                out.append(pattern[i + 1])
                i += 2
            else:
                i += 1
            continue
        if in_class:
            if c == "]":
                in_class = False
            out.append(c)
            i += 1
            continue
        # Outside a char class.
        if c == "[":
            in_class = True
            out.append(c)
            i += 1
            # A leading `]` (optionally after `^`) is a literal member, not a close.
            if i < n and pattern[i] == "^":
                out.append("^")
                i += 1
            if i < n and pattern[i] == "]":
                out.append("]")
                i += 1
            continue
        if pattern.startswith("(?<", i):
            after = pattern[i + 3] if i + 3 < n else ""
            if after not in ("=", "!"):
                out.append("(?P<")  # named group -> Python spelling
                i += 3
                continue
        out.append(c)
        i += 1
    return "".join(out)


class UnsupportedUnicodeProperty(ValueError):
    r"""A ``\p{...}`` / ``\pX`` Unicode property our authoritative resolver (the
    ``regex`` module) cannot map to a code-point set. Raised so the pipeline emits a
    clean typed outcome instead of silently mis-compiling an unknown property."""

    def __init__(self, token: str):
        super().__init__(f"unsupported unicode property: \\p{{{token}}}")
        self.token = token


class SurrogateEscapeUnmodeled(ValueError):
    r"""A UTF-16 surrogate code point (U+D800..U+DFFF) appears in the pattern, e.g.
    ``\uD807[\uDEE0-\uDEF8]`` -- a surrogate PAIR that in JS (non-``u``) denotes the
    astral range U+11EE0..U+11EF8. Python treats each half as a lone surrogate, which
    cannot even be UTF-8 encoded, and we do not model UTF-16 pairing. Raised so the
    pipeline records a clean typed outcome rather than
    crashing with UnicodeEncodeError."""

    def __init__(self, codepoint: int):
        super().__init__(f"unmodeled UTF-16 surrogate escape U+{codepoint:04X}")
        self.codepoint = codepoint


def _reject_surrogate_escapes(pattern: str) -> None:
    r"""Raise :class:`SurrogateEscapeUnmodeled` if `pattern` contains a surrogate code
    point -- as a raw char, a ``\uHHHH`` escape, or a ``\U00HHHHHH`` escape (the form
    the braced ``\u{...}`` rewrite lowers to). Backslash-run aware. Called on the
    fully-normalized pattern so every spelling funnels through one check."""
    def _is_surrogate(cp: int) -> bool:
        return 0xD800 <= cp <= 0xDFFF

    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c != "\\":
            if _is_surrogate(ord(c)):
                raise SurrogateEscapeUnmodeled(ord(c))
            i += 1
            continue
        nxt = pattern[i + 1:i + 2]
        if nxt == "u" and i + 6 <= n and all(ch in _HEX_DIGITS for ch in pattern[i + 2:i + 6]):
            cp = int(pattern[i + 2:i + 6], 16)
            if _is_surrogate(cp):
                raise SurrogateEscapeUnmodeled(cp)
            i += 6
            continue
        if nxt == "U" and i + 10 <= n and all(ch in _HEX_DIGITS for ch in pattern[i + 2:i + 10]):
            cp = int(pattern[i + 2:i + 10], 16)
            if _is_surrogate(cp):
                raise SurrogateEscapeUnmodeled(cp)
            i += 10
            continue
        # Any other escape: skip the backslash and its escaped char as a unit.
        i += 2 if i + 1 < n else 1


import functools as _functools


@_functools.lru_cache(maxsize=None)
def _unicode_property_ranges(token: str) -> tuple:
    r"""Sorted ``((start, end), ...)`` code-point ranges for the Unicode property
    `token` (the text inside ``\p{...}`` or the single letter of ``\pX``), resolved
    by the authoritative ``regex`` module. This is the single, data-driven
    property->ranges table -- not a per-regex or hand-transcribed map.

    The resolution is exact: we ask ``regex`` (which implements the full Unicode
    property database -- general categories, scripts, blocks, POSIX aliases) which
    code points match ``\p{token}`` and coalesce them into ranges. Reproducibility
    note: the resulting ranges track the Unicode version shipped with the installed
    ``regex`` module (pin it in requirements); document the version in the paper.

    Raises :class:`UnsupportedUnicodeProperty` if ``regex`` cannot compile the
    property, so nothing silently mis-compiles.
    """
    import regex as _regex
    try:
        pat = _regex.compile("\\p{" + token + "}")
    except Exception:
        raise UnsupportedUnicodeProperty(token)
    ranges: List[tuple] = []
    start = prev = None
    for cp in range(0, MAX_UNICODE + 1):
        if pat.match(chr(cp)):
            if start is None:
                start = prev = cp
            elif cp == prev + 1:
                prev = cp
            else:
                ranges.append((start, prev))
                start = prev = cp
    if start is not None:
        ranges.append((start, prev))
    return tuple(ranges)


def _complement_ranges(ranges: tuple) -> tuple:
    """Code-point ranges NOT covered by `ranges` (over U+0000..U+10FFFF)."""
    out: List[tuple] = []
    nxt = 0
    for s, e in ranges:
        if s > nxt:
            out.append((nxt, s - 1))
        nxt = e + 1
    if nxt <= MAX_UNICODE:
        out.append((nxt, MAX_UNICODE))
    return tuple(out)


def _ranges_to_class_body(ranges: tuple) -> str:
    r"""Char-class BODY (no brackets) for `ranges`, each endpoint an unambiguous
    ``\U########`` escape so it splices safely into any char class."""
    parts: List[str] = []
    for s, e in ranges:
        if s == e:
            parts.append(f"\\U{s:08X}")
        else:
            parts.append(f"\\U{s:08X}-\\U{e:08X}")
    return "".join(parts)


def _property_class_fragment(token: str, neg: bool, in_class: bool) -> str:
    r"""Regex-syntax fragment expressing Unicode property `token` as an explicit
    char set. Inside a class we splice the (possibly complemented) ranges directly;
    outside, we wrap in ``[...]`` / ``[^...]``. An empty property matches nothing."""
    ranges = _unicode_property_ranges(token)
    if in_class:
        rr = _complement_ranges(ranges) if neg else ranges
        return _ranges_to_class_body(rr)
    if neg:
        # `[^body]` matches any char NOT in the property (empty body -> matches any).
        return "[^" + _ranges_to_class_body(ranges) + "]"
    if not ranges:
        # An empty property matches nothing; `[^\x00-\U0010FFFF]` is un-satisfiable.
        return "[^\\U00000000-\\U0010FFFF]"
    return "[" + _ranges_to_class_body(ranges) + "]"


def rewrite_js_unicode_properties(pattern: str) -> str:
    r"""Rewrite Unicode property escapes ``\p{X}`` / ``\P{X}`` / ``\pX`` / ``\PX`` to
    EXPLICIT char sets Python's ``sre_parse`` (and every engine) accepts.

    Python's ``sre_parse`` has no ``\p`` support at all; JS reads it only under the
    ``u`` flag (bare ``\p`` is a literal ``p`` in non-``u`` mode, and the single-letter
    ``\pL`` form is Perl/PCRE, not even valid JS-with-``u``). A corpus author writing
    ``\p{L}`` / ``\pL`` plainly means the Unicode property, so -- **decided (human,
    )** -- each property maps to its exact code-point set (highest
    fidelity) via :func:`_unicode_property_ranges`, and emit that set as ``[...]``.
    ``_requires_u`` already flags these regexes as needing ``u``. Modeling reading
    worth a sentence in the paper.

    Semantics preserved across positions:

    * Outside a char class: ``\p{X}`` -> ``[ranges]``, ``\P{X}`` -> ``[^ranges]``.
    * Inside a class ``[... \p{X} ...]``: splice the ranges (``\P{X}`` splices the
      COMPLEMENT ranges) so ``[\p{Pd}\p{Pc}]`` and ``[\P{X}y]`` both stay correct.

    Backslash-run aware (``\\p{L}`` is an escaped backslash + literal ``p{L}``) and
    char-class aware. Raises :class:`UnsupportedUnicodeProperty` for a property the
    resolver does not know (never a silent mis-compile).
    """
    out: List[str] = []
    i, n = 0, len(pattern)
    in_class = False
    while i < n:
        c = pattern[i]
        if c == "\\":
            nxt = pattern[i + 1] if i + 1 < n else ""
            if nxt in ("p", "P"):
                neg = nxt == "P"
                token = None
                consumed_end = i
                if i + 2 < n and pattern[i + 2] == "{":
                    close = pattern.find("}", i + 3)
                    if close != -1:
                        token = pattern[i + 3:close]
                        consumed_end = close + 1
                elif i + 2 < n and pattern[i + 2].isalpha():
                    token = pattern[i + 2]  # single-letter \pL / \PL form
                    consumed_end = i + 3
                if token:
                    out.append(_property_class_fragment(token, neg, in_class))
                    i = consumed_end
                    continue
                # `\p` with empty/absent property: fall through to a verbatim copy so
                # it fails downstream exactly as before (malformed either way).
            # Generic escape: copy the backslash AND the escaped char verbatim.
            out.append(c)
            if i + 1 < n:
                out.append(pattern[i + 1])
                i += 2
            else:
                i += 1
            continue
        if in_class:
            if c == "]":
                in_class = False
            out.append(c)
            i += 1
            continue
        if c == "[":
            in_class = True
            out.append(c)
            i += 1
            if i < n and pattern[i] == "^":
                out.append("^")
                i += 1
            if i < n and pattern[i] == "]":
                out.append("]")
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def normalize_js_regex(pattern: str) -> str:
    r"""Rewrite the JS-only syntax that Python's ``sre_parse`` reads differently, so
    the SAME normalized pattern drives the grammar, the neutral oracle, and pad
    selection. Currently: empty classes (``[]`` / ``[^]``), shorthand-adjacent class
    hyphens (``[\w-\.]``), ``\p{...}`` / ``\pX`` Unicode properties (-> explicit char
    sets), ``\u{...}`` / ``\x{...}`` code points, ``\cX`` control escapes,
    ``\A \Z \z \Q \E \G \e \K`` identity escapes, and ``(?<name>...)`` / ``\k<name>``
    named groups.

    The empty-class and class-hyphen rewrites run FIRST on the raw pattern (before
    the property rewrite splices ``\U########`` ranges into classes, whose ``-`` are
    genuine ranges to leave alone); the property rewrite runs next so its emitted
    escapes and ``[...]`` are seen by the later rewrites as ordinary syntax; control
    escapes run before the identity rewrite so ``\cX`` is consumed as a unit (its
    ``c`` is never mistaken for a lone letter); the families otherwise touch disjoint
    constructs."""
    normalized = rewrite_js_named_groups(
        rewrite_js_identity_escapes(
            rewrite_js_control_escapes(
                rewrite_js_codepoint_escapes(
                    rewrite_js_unicode_properties(
                        rewrite_js_class_shorthand_ranges(
                            rewrite_js_empty_class(pattern)
                        )
                    )
                )
            )
        )
    )
    # A UTF-16 surrogate code point (raw, \uHHHH, or \U form) is unmodeled -- reject
    # it here so every spelling funnels through one check and the pipeline records a
    # clean typed outcome instead of crashing at UTF-8 encode time.
    _reject_surrogate_escapes(normalized)
    return normalized


def ANY_CHAR() -> str:
    r"""Terminal for regex ``.`` (and lookaround filler): exactly ONE code unit.

    The pipeline reads every fuzzed tree back with ``str(tree)`` and feeds that to
    the JS engines. Fandango's ``<utf8_char>`` emits a *multi-byte* UTF-8 sequence,
    but ``str(tree)`` decodes those bytes as Latin-1 -- so one logical character
    arrives at the engine as SEVERAL single-byte code units. The engine's ``.``
    (and JS ``.``) matches one code unit, so a multi-byte ``.`` never aligns to a
    single engine character. That silently breaks anything char-boundary-precise --
    most visibly backreferences: ``(.)\1`` could not produce a real match because
    the captured multi-byte char spanned several units (mojibake).

    Emitting a single code unit ``[\x00-\x7f]`` makes the grammar's notion of "one
    character" match the engine's notion of "one character" in the Latin-1 string
    that is actually fed to it. The prior multi-byte form never delivered a genuine
    astral character to the engine anyway (always a byte-run), so no real coverage
    is lost. Range matches the old ``<utf8_char1>`` (``\n`` included, as before).
    A global modeling decision, applied uniformly.
    """
    return r"r'[\x00-\x7f]'"


def DOT_CHAR() -> str:
    r"""Terminal for regex ``.`` in the default (non-DOTALL) mode: one code unit
    that is NOT a line terminator.

    JS ``.`` (and Python ``.`` without ``re.DOTALL``) matches any character EXCEPT
    a line terminator. Under the single-code-unit ASCII model of :func:`ANY_CHAR`
    (``[\x00-\x7f]``) the only line terminators in range are ``\n`` (0x0a) and
    ``\r`` (0x0d); JS additionally excludes U+2028/U+2029, but those are > 0x7f and
    already outside the ASCII cap, so nothing extra is needed here. Emitting the
    full ``[\x00-\x7f]`` for ``.`` (as before) let Fandango place a ``\n``/``\r``
    inside a ``.``-span, producing a string the regex does not actually match under
    the harness flags (no ``s``) -- a mis-compilation.

    The corpus patterns are bare (no flags) and no API harness sets the ``s`` flag,
    so non-DOTALL is the correct, uniform assumption for every regex. This is only
    for the ``.`` operator; lookaround filler keeps :func:`ANY_CHAR` (maximally
    permissive synthetic context, not a matched ``.``).
    """
    return r"r'[\x00-\x09\x0b\x0c\x0e-\x7f]'"

@dataclass
class LookassertionInfo:
    """Stores information about lookahead/lookbehind assertions"""
    position: int
    is_positive: bool
    is_lookbehind: bool
    pattern: str
    constraint_name: str
    parsed_pattern: any

@dataclass
class LookaroundInfo:
    """Stores information about lookaround assertions"""
    rule_name: str
    rule_function_name: str

@dataclass
class GrammarOutput:
    """Container for generated grammar and constraints"""
    ebnf: str
    constraints: str
    lookaheads: List[LookassertionInfo] = field(default_factory=list)
    lookbehinds: List[LookassertionInfo] = field(default_factory=list)
    generators: str = ""


@dataclass
class VisitorContext:
    """Context passed through visitor methods"""
    position: int = 0
    indent_level: int = 0
    pos_var: str = "pos"
    str_var: str = "s"
    parent_rule: str = "<start>"
    extra_escapes: bool = False  # Whether to apply extra escaping for embedding in Fandango content


class RegexNodeVisitor(ABC):
    """Abstract base class for regex pattern visitors"""
    
    @abstractmethod
    def visit_literal(self, value: int, context: VisitorContext) -> Any: pass
    @abstractmethod
    def visit_not_literal(self, value: int, context: VisitorContext) -> Any: pass
    @abstractmethod
    def visit_any(self, context: VisitorContext) -> Any: pass
    @abstractmethod
    def visit_in(self, charset: List, context: VisitorContext) -> Any: pass
    @abstractmethod
    def visit_branch(self, branches: List, context: VisitorContext) -> Any: pass
    @abstractmethod
    def visit_subpattern(self, group_num: int, pattern: List, context: VisitorContext) -> Any: pass
    @abstractmethod
    def visit_repeat(self, min_rep: int, max_rep: int, pattern: List, is_greedy: bool, context: VisitorContext) -> Any: pass
    @abstractmethod
    def visit_assert(self, direction: int, pattern: List, context: VisitorContext) -> Any: pass
    @abstractmethod
    def visit_assert_not(self, direction: int, pattern: List, context: VisitorContext) -> Any: pass
    @abstractmethod
    def visit_at(self, at_type: int, context: VisitorContext) -> Any: pass
    @abstractmethod
    def visit_category(self, category: int, context: VisitorContext) -> Any: pass


class EBNFGeneratorVisitor(RegexNodeVisitor):
    """Visitor that generates EBNF grammar rules"""
    
    def __init__(self):
        self.rule_counter = 0
        self.rules = {}
        self.assertion_rules = {}  # Maps assertion rule -> (assertion_info, parent_rule)
        self.group_to_rule = {} # Maps group_num -> rule_name, to know which rule corresponds to which assertion when we are visiting the pattern
        self.group_reference_rule_triples = [] # List of (lca, rule_name_1, rule_name_2) triples; we add constraints over this at the end
        self.parent_graph = {} # Maps parent_rule -> list of child rules, to know where to add the constraints for the assertions
    
    def _new_rule_name(self) -> str:
        name = f'<r{self.rule_counter}>'
        self.rule_counter += 1
        return name
    
    def safe_char_replace(self, char: str) -> str:
        """Replace special characters with escape sequences"""
        return _safe_char_replace(char)

    def visit_literal(self, value: int, context: VisitorContext) -> str:
        return f'"{self.safe_char_replace(chr(value))}"'
    
    def visit_not_literal(self, value: int, context: VisitorContext) -> str:
        rule_name = self._new_rule_name()
        self.rules[rule_name] = f"r\'[^{self.safe_char_replace(chr(value))}]\'"
        # Update parent graph
        if context.parent_rule not in self.parent_graph:
            self.parent_graph[context.parent_rule] = []
        self.parent_graph[context.parent_rule].append(rule_name)
        return rule_name
    
    def visit_any(self, context: VisitorContext) -> str:
        # `.` excludes line terminators in the default (non-DOTALL) mode; use the
        # newline-excluding terminal, NOT the fully-permissive ANY_CHAR (which is
        # kept for synthetic lookaround filler).
        return DOT_CHAR()
    
    def visit_in(self, charset: List, context: VisitorContext) -> str:
        char_class = self._process_charset(charset, context)
        rule_name = self._new_rule_name()
        self.rules[rule_name] = char_class
        # Update parent graph
        if context.parent_rule not in self.parent_graph:
            self.parent_graph[context.parent_rule] = []
        self.parent_graph[context.parent_rule].append(rule_name)
        return rule_name
    
    def visit_branch(self, branches: List, context: VisitorContext) -> str:
        branch_rules = []
        for i, branch in enumerate(branches):
            branch_name = self._new_rule_name()
            branch_ctx = VisitorContext(context.position, context.indent_level, 
                                       context.pos_var, context.str_var, branch_name)
            branch_result = self.visit_pattern(branch, branch_ctx)
            self.rules[branch_name] = branch_result
            branch_rules.append(branch_name)
            # Update parent graph
            if context.parent_rule not in self.parent_graph:
                self.parent_graph[context.parent_rule] = []
            self.parent_graph[context.parent_rule].append(branch_name)
        return '(' + ' | '.join(branch_rules) + ')'
    
    # Notably, this records a new non-terminal for the subpattern, and if it is a capture group, 
    # it also records the mapping from the group number to that non-terminal, so that we can refer 
    # to it when we visit group references.
    def visit_subpattern(self, group_num: int, pattern: List, context: VisitorContext) -> str:
        subpattern_rule_name = self._new_rule_name()
        subpattern_rule_content = self.visit_pattern(pattern, context)
        self.rules[subpattern_rule_name] = subpattern_rule_content
        # Only CAPTURE groups (numbered) map to a rule. A non-capturing group --
        # (?:...) or a scoped-flag group (?i:...) -- has group_num None and must NOT
        # enter group_to_rule: a None key is never referenced (backreferences are
        # numbered) and once a real numbered group coexists, `sorted(group_to_rule)`
        # compares None against an int and raises TypeError (regex_543
        # `(?i:\b(Contents|...)\b)`, an outer scoped-flag group around group 1).
        if group_num is not None:
            self.group_to_rule[group_num] = subpattern_rule_name
        # Update parent graph
        if context.parent_rule not in self.parent_graph:
            self.parent_graph[context.parent_rule] = []
        self.parent_graph[context.parent_rule].append(subpattern_rule_name)
        return subpattern_rule_name
    
    def visit_repeat(self, min_rep: int, max_rep: int, pattern: List, 
                     is_greedy: bool, context: VisitorContext) -> str:
        # We want to put these in a sub-rule, notably in case constraints require a meaningful
        # least common ancestor. This applies, e.g., for indexed backreference.

        new_rule_name = self._new_rule_name()
        saved_parent_rule = context.parent_rule
        context.parent_rule = new_rule_name  # Set the parent rule for the repeated pattern to be the new rule
        sub_rule = self.visit_pattern(pattern, context)
        self.rules[new_rule_name] = sub_rule
        context.parent_rule = saved_parent_rule  # Restore parent rule in context
        
        if min_rep == 0 and max_rep == 1:
            return f'({new_rule_name})?'
        elif min_rep == 0 and max_rep == sre_parse.MAXREPEAT:
            return f'({new_rule_name})*'
        elif min_rep == 1 and max_rep == sre_parse.MAXREPEAT:
            return f'({new_rule_name})+'
        elif min_rep == max_rep:
            return f'({new_rule_name}){{{min_rep}}}'
        else:
            max_str = '' if max_rep == sre_parse.MAXREPEAT else str(max_rep)
            return f'({new_rule_name}){{{min_rep},{max_str}}}'
    
    # TODO: Code duplication with visit_assert_not, unify
    def visit_assert(self, direction: int, pattern: List, context: VisitorContext) -> str:
        # New: I think we should translate lookaheads to:
        # rule_name ::= <whatever_the_lookahead_pattern_translates_to_e> ANY_CHAR()* 
        # and lookbehinds to:
        # rule_name ::= ANY_CHAR()* <whatever_the_lookbehind_pattern_translates_to_e>
        # The <..._e> rules are <whatever> | <e> with <e> ::= '', so it can be empty.
        # Create a new rule for the ANY_CHAR()* 
        rule_name = self._new_rule_name()
        rule_name_e = '<' + rule_name.strip('<>') + '_e>'  # We want to use this rule name in the constraint code, and it will be cleaner without the angle brackets
        
        # Update parent graph
        if context.parent_rule not in self.parent_graph:
            self.parent_graph[context.parent_rule] = []
        self.parent_graph[context.parent_rule].append(rule_name)

        # Also for <..._e>, which goes under rule_name
        if rule_name not in self.parent_graph:
            self.parent_graph[rule_name] = []
        self.parent_graph[rule_name].append(rule_name_e)

        # Get the inner pattern
        old_parent_rule = context.parent_rule
        context.parent_rule = rule_name_e  # Set the parent rule for the inner pattern to be the current rule, so that when we visit the inner pattern, we know it is under this assertion
        rule_content = self.visit_pattern(pattern, context)
        context.parent_rule = old_parent_rule  # Restore the parent rule in the context

        # What's the direction?
        if direction >= 0:
            # e.g.,
            # <r0> ::= <r0_e> ANY_CHAR()* ;
            # <r0_e> ::= <whatever the lookahead pattern translates to> | '' ;
            self.rules[rule_name] = f'{rule_name_e} {ANY_CHAR()}*'
            self.rules[rule_name_e] = f'{rule_content} | ""'
        else:
            # e.g.,
            # <r0> ::= ANY_CHAR()* <r0_e> ;
            # <r0_e> ::= <whatever the lookbehind pattern translates to> | '' ;
            self.rules[rule_name] = f'{ANY_CHAR()}* {rule_name_e}'
            self.rules[rule_name_e] = f'{rule_content} | ""'

        # For lookaheads/behinds, we will make an assertion on the generated _e rule.
        # The EBNF without constraints admits both positive and negative cases, but the 
        # constraints will enforce.
        self.assertion_rules[rule_name_e] = {
            'type': 'lookaround',
            'positive': True,
            'direction': direction,
        }
        
        return rule_name
    
    def visit_assert_old(self, direction: int, pattern: List, context: VisitorContext) -> str:
        # New: I think we should translate lookaheads to:
        # rule_name ::= <whatever_the_lookahead_pattern_translates_to_e> ANY_CHAR()* 
        # and lookbehinds to:
        # rule_name ::= ANY_CHAR()* <whatever_the_lookbehind_pattern_translates_to_e>
        # The <..._e> rules are <whatever> | <e> with <e> ::= '', so it can be empty.
        # Create a new rule for the ANY_CHAR()* 
        rule_name = self._new_rule_name()
        self.rules[rule_name] = f'{ANY_CHAR()}*'
        
        # Store mapping: this rule has an assertion, remember parent context
        self.assertion_rules[rule_name] = {
            'type': 'lookahead' if direction >= 0 else 'lookbehind',
            'positive': True,
            'pattern': pattern,
            'direction': direction,
            'parent_rule': context.parent_rule  # The rule containing this assertion
        }
        
        return rule_name
    
    def visit_assert_not(self, direction: int, pattern: List, context: VisitorContext) -> str:
                # New: I think we should translate lookaheads to:
        # rule_name ::= <whatever_the_lookahead_pattern_translates_to_e> ANY_CHAR()* 
        # and lookbehinds to:
        # rule_name ::= ANY_CHAR()* <whatever_the_lookbehind_pattern_translates_to_e>
        # The <..._e> rules are <whatever> | <e> with <e> ::= '', so it can be empty.
        # Create a new rule for the ANY_CHAR()* 
        rule_name = self._new_rule_name()
        rule_name_e = '<' + rule_name.strip('<>') + '_e>'  # We want to use this rule name in the constraint code, and it will be cleaner without the angle brackets
        
        # Update parent graph        
        if context.parent_rule not in self.parent_graph:
            self.parent_graph[context.parent_rule] = []
        self.parent_graph[context.parent_rule].append(rule_name)

        # Also for <..._e>, which goes under rule_name
        if rule_name not in self.parent_graph:
            self.parent_graph[rule_name] = []
        self.parent_graph[rule_name].append(rule_name_e)

        # Get the inner pattern
        old_parent_rule = context.parent_rule
        context.parent_rule = rule_name_e  # Set the parent rule for the inner pattern
        rule_content = self.visit_pattern(pattern, context)
        context.parent_rule = old_parent_rule  # Restore the parent rule in the context

        # What's the direction?
        if direction >= 0:
            # e.g.,
            # <r0> ::= <r0_e> ANY_CHAR()* ;
            # <r0_e> ::= <whatever the lookahead pattern translates to> | '' ;
            self.rules[rule_name] = f'{rule_name_e} {ANY_CHAR()}*'
            self.rules[rule_name_e] = f'{rule_content} | ""'
        else:
            # e.g.,
            # <r0> ::= ANY_CHAR()* <r0_e> ;
            # <r0_e> ::= <whatever the lookbehind pattern translates to> | '' ;
            self.rules[rule_name] = f'{ANY_CHAR()}* {rule_name_e}'
            self.rules[rule_name_e] = f'{rule_content} | ""'


        # For lookaheads/behinds, we will make an assertion on the generated _e rule.
        # The EBNF without constraints admits both positive and negative cases, but the 
        # constraints will enforce.
        self.assertion_rules[rule_name_e] = {
            'type': 'lookaround',
            'positive': False,
            'direction': direction,
        }
        
        return rule_name

    def visit_assert_not_old(self, direction: int, pattern: List, context: VisitorContext) -> str:
        # Create a new rule for the assertion
        rule_name = self._new_rule_name()
        self.rules[rule_name] = f'{ANY_CHAR()}*'
        
        # Store mapping
        self.assertion_rules[rule_name] = {
            'type': 'lookahead' if direction >= 0 else 'lookbehind',
            'positive': False,
            'pattern': pattern,
            'direction': direction,
            'parent_rule': context.parent_rule
        }
        
        return rule_name
    
    def visit_at(self, at_type: int, context: VisitorContext) -> str:
        return '""'
    
    def visit_category(self, category: int, context: VisitorContext) -> str:
        cat_rule = self._process_category(category)
        rule_name = self._new_rule_name()
        self.rules[rule_name] = cat_rule
        # Update parent graph
        if context.parent_rule not in self.parent_graph:
            self.parent_graph[context.parent_rule] = []
        self.parent_graph[context.parent_rule].append(rule_name)
        return rule_name
    
    def _compute_least_common_ancestor(self, rule1: str, rule2: str) -> Optional[str]:
        # Compute least common ancestor of rule1 and rule2 in the parent graph

        # Helper function to get ancestors in a graph
        # There should be no cycles ... I think
        def get_ancestors(rule: str) -> set:
            ancestors = set()
            stack = [rule]
            while stack:
                current = stack.pop()
                ancestors.add(current)
                parents = [parent for parent, children in self.parent_graph.items() if current in children]
                stack.extend(parents)
            return ancestors
        
        def get_depth(rule: str, depth=0) -> int:
            parents = [parent for parent, children in self.parent_graph.items() if rule in children]
            if not parents:
                return depth
            return max(get_depth(parent, depth + 1) for parent in parents)
        
        ancestors1 = get_ancestors(rule1)
        ancestors2 = get_ancestors(rule2)

        common_ancestors = ancestors1.intersection(ancestors2)
        if not common_ancestors:
            return None  # No common ancestor found

        # Return the one with the greatest depth (least common ancestor)
        return max(common_ancestors, key=get_depth)

    def visit_pattern(self, pattern: List, context: VisitorContext) -> str:
        """Visit a complete pattern"""
        parts = []
        for op, av in pattern:
            if op == sre_parse.LITERAL:
                parts.append(self.visit_literal(av, context))
            elif op == sre_parse.NOT_LITERAL:
                parts.append(self.visit_not_literal(av, context))
            elif op == sre_parse.ANY:
                parts.append(self.visit_any(context))
            elif op == sre_parse.IN:
                parts.append(self.visit_in(av, context))
            elif op == sre_parse.BRANCH:
                parts.append(self.visit_branch(av[1], context))
            elif op == sre_parse.SUBPATTERN:
                #print("visiting subpattern:", av)
                parts.append(self.visit_subpattern(av[0], av[3], context))
            elif op == sre_parse.MAX_REPEAT or op == sre_parse.MIN_REPEAT:
                parts.append(self.visit_repeat(av[0], av[1], av[2], op == sre_parse.MAX_REPEAT, context))
            elif op == sre_parse.ASSERT:
                parts.append(self.visit_assert(av[0], av[1], context))
            elif op == sre_parse.ASSERT_NOT:
                parts.append(self.visit_assert_not(av[0], av[1], context))
            elif op == sre_parse.AT:
                parts.append(self.visit_at(av, context))
            elif op == sre_parse.CATEGORY:
                parts.append(self.visit_category(av, context))
            elif op == sre_parse.GROUPREF:
                # This is a reference to a previously defined group, so we can just return the rule name for that group
                group_num = av
                if group_num in self.group_to_rule:
                    # NEW LOGIC
                    # First, grab the referenced rule name for this group reference
                    referenced_rule_name = self.group_to_rule[group_num]
                    # Create a new rule name for this reference
                    reference_rule_name = self._new_rule_name()
                    # This should have the same grammar as the referenced rule
                    self.rules[reference_rule_name] = self.rules[referenced_rule_name]
                    # Add the new rule to the parent relationship
                    if context.parent_rule not in self.parent_graph:
                        self.parent_graph[context.parent_rule] = []
                    self.parent_graph[context.parent_rule].append(reference_rule_name)
                    # Find the least common ancestor rule between the current context and the referenced rule, and add a constraint that these two rules must be equal under that ancestor
                    # It needs to be the least common.
                    lca_rule = self._compute_least_common_ancestor(context.parent_rule, referenced_rule_name)
                    if lca_rule is not None:
                        self.group_reference_rule_triples.append((lca_rule, reference_rule_name, referenced_rule_name))

                    # OLD LOGIC
                    # Record the pair of rules that need to be constrained to be equal
                    # self.group_reference_rule_pairs.append((reference_rule_name, referenced_rule_name))
                    # Return the new rule name for this reference
                    parts.append(reference_rule_name)
                else:
                    # Recall we are targeting JavaScript; forward group references are not allowed,
                    # so this should never happen in a valid regex.
                    raise ValueError(f"Group reference to undefined group number: {group_num}")
        
        return ' '.join(parts)
    
    # Positive character-set body for each shorthand category, plus whether the
    # shorthand is a *negated* one (\D \S \W). The body is always the POSITIVE set
    # (e.g. '0-9' for both \d and \D); the flag says whether the class should match
    # the complement of that set. Keeping one positive body per pair is what lets us
    # emit a correct standalone `r'[^...]'` for a negated shorthand instead of the
    # old `^0-9` fragment that only works as the first item of a whole class.
    _CATEGORY_POSITIVE_BODY = {
        sre_parse.CATEGORY_DIGIT: ('0-9', False),
        sre_parse.CATEGORY_NOT_DIGIT: ('0-9', True),
        sre_parse.CATEGORY_SPACE: (' \\t\\n\\r\\f\\v', False),
        sre_parse.CATEGORY_NOT_SPACE: (' \\t\\n\\r\\f\\v', True),
        sre_parse.CATEGORY_WORD: ('a-zA-Z0-9_', False),
        sre_parse.CATEGORY_NOT_WORD: ('a-zA-Z0-9_', True),
    }

    def _category_parts(self, category: int) -> tuple[str, bool]:
        """Return ``(positive_set_body, is_negated)`` for a shorthand category.

        Unknown categories fall back to "any byte" (matching the transpiler's prior
        permissive behavior), positive and un-negated.
        """
        return self._CATEGORY_POSITIVE_BODY.get(category, ('\\x00-\\xff', False))

    @staticmethod
    def _expand_class_body(body: str) -> set:
        r"""Expand a char-class body string (e.g. ``'0-9'``, ``' \t\n\r\f\v'``,
        ``'a-zA-Z0-9_'``) into the set of code points it denotes.

        The body is a fragment as it appears inside ``[...]``: backslash escapes
        (``\t \n \r \f \v \xNN``) and ``X-Y`` ranges. Escapes are decoded first,
        then ranges are coalesced back to their members. Only ever fed the entries
        of ``_CATEGORY_POSITIVE_BODY`` -- the single source of truth for what each
        ``\s``/``\w``/``\d`` means (see the consistency note in
        ``_negated_intersection_class``).
        """
        decoded = body.encode('latin-1').decode('unicode_escape')
        result: set = set()
        i, n = 0, len(decoded)
        while i < n:
            if i + 2 < n and decoded[i + 1] == '-':
                result.update(range(ord(decoded[i]), ord(decoded[i + 2]) + 1))
                i += 3
            else:
                result.add(ord(decoded[i]))
                i += 1
        return result

    def _category_codepoints(self, category: int) -> tuple[set, bool]:
        """``(positive_set_as_code_points, is_negated)`` for a shorthand category."""
        body, is_neg = self._category_parts(category)
        return self._expand_class_body(body), is_neg

    # Whitespace controls rendered as escape sequences (matching how the
    # _CATEGORY_POSITIVE_BODY table spells \s), so an emitted class never carries
    # a raw control byte.
    _WS_CONTROL_ESCAPES = {0x09: '\\t', 0x0a: '\\n', 0x0b: '\\v',
                           0x0c: '\\f', 0x0d: '\\r'}

    def _codepoint_repr(self, cp: int) -> str:
        """Render one code point for use inside an emitted ``r'[...]'`` body."""
        if cp in self._WS_CONTROL_ESCAPES:
            return self._WS_CONTROL_ESCAPES[cp]
        # Printable ASCII passes through EXCEPT the three characters whose meaning
        # changes inside [...] -- ``-`` (range op), ``^`` (negation), ``]`` (class
        # close). A complement (see _ascii_complement_class) can place any of them as
        # a lone member; emitted raw it would silently alter the class, so hex-escape
        # it. (``\`` and quotes/whitespace are already handled by safe_char_replace.)
        if 0x20 <= cp < 0x7f and chr(cp) not in "-^]":
            return self.safe_char_replace(chr(cp))
        return f'\\x{cp:02x}'

    def _codepoints_to_class_body(self, codepoints: set) -> str:
        """Serialize a code-point set to a class body, coalescing runs of >=3
        consecutive points into ``X-Y`` ranges (shorter runs stay as singles)."""
        cps = sorted(codepoints)
        parts: List[str] = []
        i, n = 0, len(cps)
        while i < n:
            j = i
            while j + 1 < n and cps[j + 1] == cps[j] + 1:
                j += 1
            if j - i + 1 >= 3:
                parts.append(f'{self._codepoint_repr(cps[i])}-{self._codepoint_repr(cps[j])}')
            else:
                parts.extend(self._codepoint_repr(cps[k]) for k in range(i, j + 1))
            i = j + 1
        return ''.join(parts)

    def _negated_intersection_class(self, charset: List, context: VisitorContext) -> str:
        r"""Emit a positive ``r'[...]'`` for ``[^ ... ]`` that contains a negated
        shorthand (``\S`` ``\D`` ``\W``).

        Such a class is a SET INTERSECTION, not a union: by De Morgan
        ``[^ i1 i2 ... ]`` = intersection over items of ``comp(item)``. A negated
        shorthand double-negates to its finite positive set
        (``comp(\S)=\s``, ``comp(\D)=\d``, ``comp(\W)=\w``), which BOUNDS the whole
        class to a small finite set computable here:

            candidate = intersection of the positive body of each negated shorthand
            result    = candidate - union of every positive item (literals, ranges,
                        positive categories \d \s \w)

        The sets come from the transpiler's own ``_CATEGORY_POSITIVE_BODY`` table,
        NOT Python ``re``: they disagree (``re``'s ``\s`` over ASCII also matches
        ``\x1c-\x1f``), and using ``re`` would silently make ``[^\S\n]`` denote a
        different "whitespace" than every other ``\s`` in the codebase.

        A class that reduces to the empty set (e.g. ``[^\S\s]``, ``[^\W\w\D\d]``)
        can generate no character -- that is genuinely degenerate, so we keep
        failing loud (with a narrowed message) rather than emit an unsatisfiable
        rule.
        """
        candidate: set = None
        subtract: set = set()
        for op, av in charset:
            if op == sre_parse.NEGATE:
                continue
            elif op == sre_parse.LITERAL:
                subtract.add(av)
            elif op == sre_parse.RANGE:
                subtract.update(range(av[0], av[1] + 1))
            elif op == sre_parse.CATEGORY:
                body_set, is_neg = self._category_codepoints(av)
                if is_neg:
                    candidate = body_set if candidate is None else (candidate & body_set)
                else:
                    subtract |= body_set

        result = (candidate or set()) - subtract
        if not result:
            raise NotImplementedError(
                "character class denotes the empty set after intersecting an overall "
                f"negation with a negated shorthand: {charset!r}. A rule that can "
                "generate no character is unsatisfiable -- recorded as error."
            )
        body = self._maybe_extra_escape(self._codepoints_to_class_body(result), context)
        return f"r'[{body}]'"

    # The transpiler's single-code-unit character universe: ANY_CHAR and DOT_CHAR
    # are [\x00-\x7f], so a negated class's complement is taken over this range.
    _ASCII_UNIVERSE = frozenset(range(0x00, 0x80))

    # Positive shorthands -> their real regex token, used to test category membership
    # with Python `re` (the generation ORACLE) rather than the transpiler's own
    # _CATEGORY table. Only positive shorthands reach the complement path (a negated
    # shorthand under overall negation is the intersection case handled elsewhere).
    _SRE_CATEGORY_TO_SHORTHAND = {
        sre_parse.CATEGORY_DIGIT: r'\d', sre_parse.CATEGORY_NOT_DIGIT: r'\D',
        sre_parse.CATEGORY_SPACE: r'\s', sre_parse.CATEGORY_NOT_SPACE: r'\S',
        sre_parse.CATEGORY_WORD: r'\w', sre_parse.CATEGORY_NOT_WORD: r'\W',
    }

    def _ascii_complement_class(self, charset: List, context: VisitorContext) -> str:
        r"""Positive ``r'[...]'`` for an overall-negated class ``[^ ...]`` whose items
        are all POSITIVE (literals, ranges, positive shorthands ``\d \s \w``).

        Emitting ``r'[^body]'`` and letting exrex negate is unreliable: exrex samples
        a negated class only from printable ASCII, so excluding all of it yields an
        empty pool (regex_765 ``[^\x09-\x7f]`` -> IndexError). We instead keep every
        code point in the transpiler's ASCII universe (``[\x00-\x7f]``, matching
        ANY_CHAR/DOT_CHAR) that the class EXCLUDES, and emit those as a positive class.

        Category membership is decided by Python ``re`` -- the generation oracle --
        NOT the transpiler's narrower ``_CATEGORY`` table: ``re``'s ``\s`` also matches
        ``\x1c-\x1f``, so a table-based complement would emit those for ``[^\s]`` and
        they would NOT match ``[^\s]`` under the oracle (a mis-compilation). Every code
        point we keep is one ``re`` confirms is outside the class, so ``[^...]`` matches
        it. An empty complement means the class excludes every ASCII code unit --
        unsatisfiable under this character model -- so we fail loud (recorded as an
        error). A class MIXING overall negation with a *negated* shorthand is a set
        intersection handled earlier by ``_negated_intersection_class``, so every
        category reaching here is positive (its members are excluded)."""
        literals: set = set()
        ranges: List[tuple] = []
        category_res: List = []
        for op, av in charset:
            if op == sre_parse.NEGATE:
                continue
            elif op == sre_parse.LITERAL:
                literals.add(av)
            elif op == sre_parse.RANGE:
                ranges.append((av[0], av[1]))
            elif op == sre_parse.CATEGORY:
                shorthand = self._SRE_CATEGORY_TO_SHORTHAND.get(av)
                if shorthand is None:
                    raise NotImplementedError(
                        f"unsupported category {av!r} in negated class {charset!r}")
                category_res.append(re.compile(shorthand))

        def _excluded(cp: int) -> bool:
            if cp in literals or any(lo <= cp <= hi for lo, hi in ranges):
                return True
            ch = chr(cp)
            return any(rx.match(ch) for rx in category_res)

        result = {cp for cp in self._ASCII_UNIVERSE if not _excluded(cp)}
        if not result:
            raise NotImplementedError(
                "negated character class excludes every ASCII code unit and so can "
                f"generate nothing under the transpiler's ASCII model: {charset!r}."
            )
        body = self._maybe_extra_escape(self._codepoints_to_class_body(result), context)
        return f"r'[{body}]'"

    def _maybe_extra_escape(self, body: str, context: VisitorContext) -> str:
        """Escape ``]`` and ``'`` when the class will be embedded in a Python string.

        Only relevant for lookaround sub-specs (``extra_escapes``); category bodies
        never contain either character, so this is a no-op for them.
        """
        if context.extra_escapes:
            return body.replace(']', '\\]').replace("'", "\\'")
        return body

    def _escape_class_literal(self, char: str, context: VisitorContext) -> str:
        r"""Escape one LITERAL character for safe emission inside ``r'[...]'``.

        Inside a class the characters ``-`` (range operator), ``^`` (negation when
        first), and ``]`` (class close) change SET MEMBERSHIP, so a *literal* one
        must be backslash-escaped or it is silently reinterpreted -- e.g. a literal
        ``\-`` was being emitted as a bare ``-`` and became a range (``[a\-z]`` ->
        ``r'[a-z]'``, matching every lowercase letter). ``\`` and whitespace/quotes
        are already handled by :meth:`safe_char_replace`.

        ``]`` is only escaped here when NOT in an ``extra_escapes`` (lookaround)
        context; there :meth:`_maybe_extra_escape` escapes it instead, so doing both
        would double-escape. ``-``/``^`` are not touched by that path, so they are
        always escaped here.
        """
        if char in ("-", "^"):
            return "\\" + char
        if char == "]" and not context.extra_escapes:
            return "\\]"
        return self.safe_char_replace(char)

    def _process_charset(self, charset: List, context: VisitorContext) -> str:
        r"""Translate an ``sre`` character set into a Fandango single-char terminal.

        A negated shorthand (\D \S \W) cannot be inlined into a positive ``[...]``:
        the old code appended ``^0-9`` mid-class, dropping the negation and leaving
        a stray literal ``^`` (e.g. ``[\s\S]`` became ``r'[ \t\n\r\f\v^ \t\n\r\f\v]'``).
        Instead we express each negated shorthand as its own standalone ``r'[^...]'``
        and UNION the whole class as an EBNF alternation of single-char terminals,
        which Fandango samples correctly.

        Overall class negation (``[^...]``) is applied by negating the positive
        ``r'[...]'``. Combining overall negation WITH a negated shorthand needs set
        intersection (``[^\S\n]`` = whitespace minus newlines), which a union of
        alternatives cannot express -- that case is handled by computing the finite
        result set directly (see ``_negated_intersection_class``).
        """
        positive_parts: List[str] = []   # literals, ranges, positive shorthands -> one r'[...]'
        negated_bodies: List[str] = []   # each negated shorthand -> its own r'[^...]'
        negate = False

        for op, av in charset:
            if op == sre_parse.NEGATE:
                negate = True
            elif op == sre_parse.LITERAL:
                positive_parts.append(self._escape_class_literal(chr(av), context))
            elif op == sre_parse.RANGE:
                # The `-` BETWEEN the endpoints is the range operator (kept); only the
                # endpoint characters are escaped as literals.
                positive_parts.append(
                    f'{self._escape_class_literal(chr(av[0]), context)}-'
                    f'{self._escape_class_literal(chr(av[1]), context)}'
                )
            elif op == sre_parse.CATEGORY:
                body, is_neg = self._category_parts(av)
                (negated_bodies if is_neg else positive_parts).append(body)

        if negate and negated_bodies:
            # Overall negation + a negated shorthand denotes a SET INTERSECTION,
            # which the union-based path above cannot express. It is finite and
            # computable at transpile time -- see _negated_intersection_class.
            return self._negated_intersection_class(charset, context)

        # Overall-negated class with only positive items. We do NOT emit r'[^body]'
        # and let the fuzzer negate: exrex draws a negated class only from its
        # printable-ASCII universe (0x20-0x7e), so a class excluding all of it (e.g.
        # [^\x09-\x7f], regex_765) leaves an empty pool -> IndexError at fuzz time.
        # Instead compute the complement explicitly over the transpiler's ASCII
        # universe and emit it as a positive class (deterministic, exrex-safe).
        if negate:
            return self._ascii_complement_class(charset, context)

        # Positive class: union the positive items and each negated shorthand.
        alternatives: List[str] = []
        if positive_parts:
            body = self._maybe_extra_escape(''.join(positive_parts), context)
            alternatives.append(f"r'[{body}]'")
        for neg_body in negated_bodies:
            body = self._maybe_extra_escape(neg_body, context)
            alternatives.append(f"r'[^{body}]'")

        if not alternatives:
            # Empty class (no items at all): should not arise from valid regex, but
            # keep it well-formed rather than emitting `r'[]'`.
            return "r'[\\x00-\\xff]'"
        if len(alternatives) == 1:
            return alternatives[0]
        return '(' + ' | '.join(alternatives) + ')'

    def _process_category(self, category: int) -> str:
        """Single-char Fandango terminal for a standalone shorthand category.

        Used by ``visit_category`` (a shorthand appearing outside any ``[...]``).
        Inside a char set, ``_process_charset`` handles categories directly.
        """
        body, is_neg = self._category_parts(category)
        return f"r'[^{body}]'" if is_neg else f"r'[{body}]'"


class ConstraintGeneratorVisitor(RegexNodeVisitor):
    """Visitor that generates constraint validation code"""
    
    def __init__(self):
        self.lookaround_counter = 0
        self.lookaheads = []
        self.lookbehinds = []
        self.constraints = []
        self.generators = {} # Maps rule_name -> generator code for generating strings that satisfy the assertion
        self.parsers = {} # Maps rule_name -> parser code for validating the assertion
        self.group_to_rule = {} # Maps group_num -> rule_name, to know which rule corresponds to which assertion when we are visiting the pattern
    
    def safe_char_replace(self, char: str) -> str:
        """Replace special characters with escape sequences"""
        return _safe_char_replace(char)

    def visit_literal(self, value: int, ctx: VisitorContext) -> List[str]:
        char = self.safe_char_replace(chr(value))
        ind = '    ' * ctx.indent_level
        return [
            f"{ind}if {ctx.pos_var} >= len({ctx.str_var}) or {ctx.str_var}[{ctx.pos_var}] != '{char}':",
            f"{ind}    return False",
            f"{ind}{ctx.pos_var} += 1"
        ]
    
    def visit_not_literal(self, value: int, ctx: VisitorContext) -> List[str]:
        return []
    
    def visit_any(self, ctx: VisitorContext) -> List[str]:
        return []
    
    def visit_in(self, charset: List, ctx: VisitorContext) -> List[str]:
        return []
    
    def visit_branch(self, branches: List, ctx: VisitorContext) -> List[str]:
        return []
    
    def visit_subpattern(self, group_num: int, pattern: List, ctx: VisitorContext) -> List[str]:
        return self.visit_pattern(pattern, ctx)
    
    def visit_repeat(self, min_rep: int, max_rep: int, pattern: List, 
                     is_greedy: bool, ctx: VisitorContext) -> List[str]:
        return []
    
    def visit_assert(self, direction: int, pattern: List, ctx: VisitorContext) -> List[str]:
        return []
    
    def visit_assert_not(self, direction: int, pattern: List, ctx: VisitorContext) -> List[str]:
        return []
    
    def visit_at(self, at_type: int, ctx: VisitorContext) -> List[str]:
        return []
    
    def visit_category(self, category: int, ctx: VisitorContext) -> List[str]:
        return []
    
    def visit_pattern(self, pattern: List, ctx: VisitorContext) -> List[str]:
        lines = []
        #print("Visiting pattern for constraint generation:", pattern)
        for op, av in pattern:
            if op == sre_parse.LITERAL:
                lines.extend(self.visit_literal(av, ctx))
            elif op == sre_parse.SUBPATTERN:
                lines.extend(self.visit_subpattern(av[0], av[3], ctx))
        return lines
    
    def prepare_fan_content_for_embedding(self, fan_content: str) -> str:
        """Prepare Fandango content for embedding in a Python string by escaping:
           - \n, \f, \r, \v
           - also ] and ' if they are in a r'[...]' character class, to avoid prematurely closing the character class or the string literal.
        """
        fan_content_space_escaped = fan_content.replace('\\n', '\\\\n').replace('\\r', '\\\\r').replace('\\f', '\\\\f').replace('\\v', '\\\\v')
        # fan_content_other_escaped = fan_content_space_escaped.replace(']', '\\]').replace("'", "\\'")
        return fan_content_space_escaped

    def make_parser_definition(self, parser_name: str, rule_id: str) -> str:
        """Create a parser function definition that uses a Fandango instance to parse strings according to the assertion's specification.
           The parser will create a Fandango instance with the provided fan_content, and attempt to parse the input string with it.
           The parser will cache this instance, so it only gets generated once per campaign.
        @param parser_name: The name of the parser function to create
        @param rule_id: A unique identifier for the rule, typically the rule name stripped of <>. This is used for creating the cache variables.
        """

        # We are assuming that make_generator_definition has already created the specification,
        # so we can reuse it. It should also be the same name as this one.

        parser_def = f"""
def {parser_name}(tree_as_str):
    global {rule_id}_OPENED, {rule_id}_fandango_instance
    if not {rule_id}_OPENED:
        {rule_id}_fandango_instance = fandango.Fandango({rule_id}_fan_content, use_cache=False)
        {rule_id}_OPENED = True
    try:
        {rule_id}_fandango_instance.parse(tree_as_str)
    except Exception:
        return False
    return True        
"""
        
        return parser_def

    def make_generator_definition(self, generator_name: str, rule_id: str, fan_content: str) -> str:
        """
        Create a generator function definition that uses a Fandango instance to generate strings that satisfy the assertion.
        The generator will create a Fandango instance with the provided fan_content, and yield strings generated by it.
        The generator will cache this instance, so it only gets generated once per campaign, and will loop through the generated strings indefinitely.

        The generator explicitly encodes the generated strings to bytes using utf-8 encoding with surrogatepass error handling, to ensure that any generated string can be returned as bytes without encoding errors. 
        The parser should decode using the same encoding and error handling to correctly interpret these strings.

        Inner generation is capped at 10 generations for efficiency, especially since the the inner string grammars tend to be more simple.
        
        @param generator_name: The name of the generator function to create
        @param rule_id: A unique identifier for the rule, typically the rule name stripped of <>. This is used for creating the cache variables.
        @param fan_content: The Fandango specification to use for generating strings that satisfy the assertion
        """

        # A few extra escapes are needed for embedding the fan content in a Python string, so we prepare the fan content by replacing backslashes and quotes with escape sequences
        fan_content_extra_escapes = self.prepare_fan_content_for_embedding(fan_content)

        gen_def = f'''
{rule_id}_OPENED = False
{rule_id}_fandango_instance = None
{rule_id}_cached_results = None
{rule_id}_pos_counter = 0

{rule_id}_fan_content = """
{fan_content_extra_escapes}
"""

def {generator_name}():
    global {rule_id}_OPENED, {rule_id}_fandango_instance, {rule_id}_cached_results, {rule_id}_pos_counter
    # Ask a sub-instance of Fandango to generate names.
    # Caching for efficiency
    if not {rule_id}_OPENED:
        {rule_id}_fandango_instance = fandango.Fandango({rule_id}_fan_content, use_cache=False)
        {rule_id}_cached_results = {rule_id}_fandango_instance.fuzz(desired_solutions=100, max_generations=10)
        {rule_id}_OPENED = True
    result = str({rule_id}_cached_results[{rule_id}_pos_counter]) # Return the next name in the cached results, and loop back to the beginning when we reach the end
    {rule_id}_pos_counter = ({rule_id}_pos_counter + 1) % len({rule_id}_cached_results)
    return result.encode(encoding='utf-8', errors='surrogatepass')
'''

        return gen_def

    def process_assertion(self, rule_name: str, assertion_info: Dict, parent_rule: str):
        """Process an assertion and generate its constraint"""
        pattern = assertion_info['pattern']
        is_positive = assertion_info['positive']
        direction = assertion_info['direction']

        # Slight change of plans. To handle this, we will build a generator for the lookahead/lookbehind
        # that ensures that the constraint is satisfied.
        # Create a new visitor
        inner_translator = RegexToFandangoTranslator()

        # Get the sub-specification from the pattern
        # Note, pattern isn't a string.
        inner_fan_content = inner_translator.generate_ebnf_grammar_with_constraints_from_subpattern(pattern)

        # Make a name for the generator function we will create.
        rule_name_stripped = rule_name.strip('<>')
        generator_name = f"{rule_name_stripped}_generator"

        # Make the generator function
        # ...really doesn't need to be a method but wte
        generator_definition = self.make_generator_definition(generator_name, rule_name_stripped, inner_fan_content)

        # Store the generator code for this assertion
        self.generators[rule_name] = (generator_name, generator_definition)

        if direction < 0:
            self._process_lookbehind(pattern, rule_name, is_positive)
        else:
            self._process_lookahead(pattern, rule_name, is_positive)
    
    def add_constraint_for_lookaround(self, constraint_name: str, parser_name: str, is_positive: bool, rule_name: str):
        """Add a constraint function for a lookaround assertion that uses the provided parser to validate the assertion
        The translation of b to a str from a derivation tree is done here."""
        assertion_type = "lookahead" if "lookahead" in constraint_name else "lookbehind"
        optional_negation = "" if is_positive else "not "
        positivity = "Positive" if is_positive else "Negative"
        self.constraints.append(f'''def {constraint_name}(b):
    """{positivity} {assertion_type}: must {optional_negation}match {rule_name}"""
    return {optional_negation}{parser_name}(str(b))
''')

    def _process_lookahead(self, pattern, rule_name, is_positive):
        name = f'lookahead_{self.lookaround_counter}'
        self.lookaround_counter += 1
        
        rule_name_stripped = rule_name.strip('<>')
        parser_name = f"{rule_name_stripped}_parser"
        # We are going to match the rule by parsing it with a Fandango instance that has this assertion's specification.
        generated_parser = self.make_parser_definition(parser_name, rule_name_stripped)

        # Record the parser we need to add
        self.parsers[rule_name] = generated_parser

        # Lookaheads are simpler now that we can simply parse.
        # This gets the `where ...` sorted.
        rule_function_name = name
        self.lookaheads.append(LookaroundInfo(rule_name=rule_name, rule_function_name=rule_function_name))

        # Generate the constraint code that uses the parser
        # This ensures that the function to parse the lookahead assertion is generated.
        self.add_constraint_for_lookaround(name, parser_name, is_positive, rule_name)
    
    def _process_lookbehind(self, pattern, rule_name, is_positive):
        name = f'lookbehind_{self.lookaround_counter}'
        self.lookaround_counter += 1
        
        rule_name_stripped = rule_name.strip('<>')
        parser_name = f"{rule_name_stripped}_parser"
        # We are going to match the rule by parsing it with a Fandango instance that has this assertion's specification.
        generated_parser = self.make_parser_definition(parser_name, rule_name_stripped)

        # Record the parser we need to add
        self.parsers[rule_name] = generated_parser

        # Lookbehinds are simpler now that we can simply parse.
        # This gets the `where ...` sorted.
        rule_function_name = name
        self.lookbehinds.append(LookaroundInfo(rule_name=rule_name, rule_function_name=rule_function_name))

        # Generate the constraint code that uses the parser
        # This ensures that the function to parse the lookbehind assertion is generated.
        self.add_constraint_for_lookaround(name, parser_name, is_positive, rule_name)

class RegexToFandangoTranslator:
    """Main translator using visitor pattern"""
    
    def __init__(self):
        self.ebnf_visitor = EBNFGeneratorVisitor()
        self.constraint_visitor = ConstraintGeneratorVisitor()
    
    def reset(self): # Reset internal state for new translation
        self.ebnf_visitor = EBNFGeneratorVisitor()
        self.constraint_visitor = ConstraintGeneratorVisitor()

    def make_fan_file_content(self, regex_pattern: str, grammar_output: GrammarOutput) -> str:
        """Helper to format the final Fandango file content"""
        # The provenance comment must stay a single ASCII line: a raw newline in the
        # pattern (e.g. regex_1829 `\r\n|\r` with literal CR/LF) would split the
        # comment and inject stray tokens, and a non-encodable char (regex_687) would
        # raise UnicodeEncodeError when the file is written. unicode_escape makes the
        # pattern one safe, reversible ASCII line.
        safe_pattern = regex_pattern.encode('unicode_escape').decode('ascii')
        fan_file_content = f'# regex: {safe_pattern}\n\n# Grammar:\n\n{grammar_output.ebnf}\n\n# Constraints:\n\n{grammar_output.constraints}\n\n# Generators:\n\n{grammar_output.generators}'
        return fan_file_content

    def generate_ebnf_grammar_with_constraints(self, regex_pattern: str) -> tuple[str, int]:
        """Generate EBNF grammar and constraints from a regex string.
         Returns the EBNF grammar and constraints as strings, also the number of generated constraints for reference."""
        # Reset the generator in case it's mid-use
        self.reset()
        
        # Translate the regex pattern to EBNF and constraints
        result = self.translate(regex_pattern)

        # How many constraints did we generate?
        # Check num items in ebnf_visitor.assertion_rules for lookaround assertions, 
        # and also in ebnf_visitor.group_reference_rule_triples for capture group reference constraints
        num_lookaround_constraints = len(self.ebnf_visitor.assertion_rules)
        num_capture_group_reference_constraints = len(self.ebnf_visitor.group_reference_rule_triples)
        num_constraints = num_lookaround_constraints + num_capture_group_reference_constraints

        # Prepare and return the final Fandango file content
        fan_file_content = self.make_fan_file_content(regex_pattern, result)

        # If num_constraints > 0, add an import to fandango at the top of the file content for the generator functions
        if num_constraints > 0:
            fan_file_content = 'import fandango\n\n' + fan_file_content

        return fan_file_content, num_constraints
    
    def generate_ebnf_grammar_with_constraints_from_subpattern(self, pattern: List) -> str:
        """Generate EBNF grammar and constraints from a pre-parsed subpattern
        This is useful for processing lookahead/lookbehind patterns directly."""
        self.reset()

        result = self.translate(pattern, already_parsed = True)

        # str(pattern) isn't perfect, and it looks ugly, but we don't have a better option rn.
        fan_file_content = self.make_fan_file_content(str(pattern), result)
        return fan_file_content
        

    def translate(self, regex_pattern: str, *, already_parsed = False) -> GrammarOutput:
        if not already_parsed:
            # Normalize JS-only escapes that sre_parse reads differently: braced
            # code points (\u{...}) and the \A/\Z/\z identity escapes (literal
            # letters in JS, not anchors). Uniform for every regex.
            regex_pattern = normalize_js_regex(regex_pattern)
            try:
                parsed = sre_parse.parse(regex_pattern)
            except Exception as e:
                raise ValueError(f"Invalid regex pattern: {e}")
        else:
            parsed = regex_pattern
        
        ctx = VisitorContext(position=0, parent_rule="<start>", extra_escapes=already_parsed)
        main_rule = self.ebnf_visitor.visit_pattern(parsed, ctx)
        self.ebnf_visitor.rules['<start>'] = main_rule
        
        add_lookup_helper = False

        # Process lookaround assertions
        lookaround_constraints = []
        for rule_name, assertion_info in self.ebnf_visitor.assertion_rules.items():
            # New: We have a few specific where clauses we generate for this
            # If lookahead is positive
            if assertion_info['type'] == 'lookaround':
                if assertion_info['direction'] >= 0:
                    if assertion_info['positive']:
                        # Positive lookahead
                        # where str(rule_name) != ''
                        lookaround_constraints.append(f'where {rule_name} != ""')
                    else:
                        # Negative lookahead
                        # where str(rule_name) == ''
                        # TODO -- we may want to add an additional constraint on the "rest"? 
                        lookaround_constraints.append(f'where {rule_name} == ""')
                else:
                    if assertion_info['positive']:
                        # Positive lookbehind
                        # where str(rule_name) != ''
                        lookaround_constraints.append(f'where {rule_name} != ""')
                    else:
                        # Negative lookbehind
                        # where str(rule_name) == ''
                        # TODO -- we may want to add an additional constraint on the "rest"? 
                        lookaround_constraints.append(f'where {rule_name} == ""')
    
        capture_group_constraint_defs = []
        capture_group_where_clauses = []

        # Process group references
        for lca_rule, reference_rule_name, referenced_rule_name in self.ebnf_visitor.group_reference_rule_triples:
            add_lookup_helper = True # Any one constraint is enough to require the helper function

            # quick note on lca_rule, this is the least common ancestor rule between the indexed backreference
            # and the group it refers to. We used to use it, but I don't think we do now, since the latest_matched_group
            # logic paired with the all(...) constraints seems to work things out fine. Keeping it around just in case,
            # but if we want to clean things up later after things are working, we can drop it

            # e.g., where has_preceeding_group("<r1>", <r3>)
            where_exists_clause = f'where has_preceeding_group("{referenced_rule_name}", {reference_rule_name})'
            
            # e.g., where all(<item> == str(latest_matched_group("<r1>", <item>)) for <item> in *<rs>)
            where_group_ref_clause = f'where all(<item> == str(latest_matched_group("{referenced_rule_name}", <item>)) for <item> in *{reference_rule_name})'

            capture_group_where_clauses.append(where_exists_clause)
            capture_group_where_clauses.append(where_group_ref_clause)

        # Collect generator definitions
        generator_defs = [gen_def for _, gen_def in self.constraint_visitor.generators.values()]

        # Add parsers
        parser_defs = [parser_def for parser_def in self.constraint_visitor.parsers.values()]

        # Collapse them into a string
        generators_str = '\n\n'.join(generator_defs)

        # ... Just add the parser definitions after
        parser_str = '\n\n'.join(parser_defs)

        # Combine
        combined_str = f'{generators_str}\n\n{parser_str}' if parser_str else generators_str

        # Constraints
        # I don't think we need this anymore.
        # constraints_str = self._build_constraints()
        constraints_str = '# Constraints\n\n' + '\n'.join(lookaround_constraints) if lookaround_constraints else '# No lookaround constraints\n'

        # extend with the constraints for the capture group references
        if capture_group_where_clauses:
            constraints_str += '\n\n# Capture group reference constraints\n\n' + '\n'.join(capture_group_where_clauses)

        if add_lookup_helper:
            # also doesn't have to be self. really but hey
            lookup_helper_str = self.gen_lookup_helper_functions()
            combined_str = lookup_helper_str + combined_str
            
        # Add capture group constraint definitions at the end of the combined string, since they may depend on the lookup helper function
        if capture_group_constraint_defs:
            combined_str += '\n\n# Capture group reference constraint definitions\n\n' + '\n\n'.join(capture_group_constraint_defs)

        return GrammarOutput(
            ebnf=self._build_ebnf(),
            constraints=constraints_str,
            lookaheads=self.constraint_visitor.lookaheads,
            lookbehinds=self.constraint_visitor.lookbehinds,
            generators=combined_str
        )
    
    def _build_ebnf(self) -> str:
        lines = ['# Generated EBNF Grammar for Fandango Fuzzer', '']

        # A rule whose right-hand side is empty represents the empty match (an empty
        # alternation branch such as the "end" arm of `(end|endblock)`, which
        # sre_parse factors to a BRANCH with an empty `[]` branch, or a trailing `|`,
        # or an empty group `()`). Fandango rejects a bare `<r> ::= ` (FandangoSyntaxError);
        # the empty string must be written explicitly as `""`.
        def _rhs(defn: str) -> str:
            return defn if defn.strip() else '""'

        # Build start rule
        lines.append(f'<start> ::= {_rhs(self.ebnf_visitor.rules["<start>"])}')
        lines.append('')

        # Add other rules with where clauses
        for name, defn in self.ebnf_visitor.rules.items():
            if name != '<start>':
                rule_line = f'{name} ::= {_rhs(defn)}'
                
                # Check if this rule has a generator
                if name in self.constraint_visitor.generators:
                    # Don't need the code for this one.
                    generator_name, _ = self.constraint_visitor.generators[name]
                    rule_line += " := " + generator_name + "()"  # Use the generator function for this rule

                lines.append(rule_line)

        # Add the constraints
        for lookahead in self.constraint_visitor.lookaheads:
            constraint_line = f'where {lookahead.rule_function_name}({lookahead.rule_name})'
            lines.append(constraint_line)

        for lookbehind in self.constraint_visitor.lookbehinds:
            constraint_line = f'where {lookbehind.rule_function_name}({lookbehind.rule_name})'
            lines.append(constraint_line)
        
        return '\n'.join(lines)
    
    def gen_lookup_helper_functions(self) -> str:
        """Generate helper functions for indexed backreference lookups.
        Note: requires the lightly modified version of Fandango, where we added the limit to find_subtrees
        """
        helper_functions = '''
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
'''
        return helper_functions 

    def _build_constraints(self) -> str:
        if not self.constraint_visitor.constraints:
            return '# No constraints\n'
        
        lines = ['# Lookahead/Lookbehind constraint functions', '']
        lines.extend(self.constraint_visitor.constraints)
        
        return '\n'.join(lines)

__all__ = [
    "RegexToFandangoTranslator"
]
"""
def main():
    translator = RegexToFandangoTranslator()
    
    regex1 = 
    result1 = translator.generate_ebnf_grammar_with_constraints(regex1)
    
    print(result1)

    
if __name__ == '__main__':
    main()
"""

if __name__ == '__main__':
    # Testing \b
    # Doesn't work yet, we would need a constraint for \b and \B
    # translator = RegexToFandangoTranslator()
    
    # regex1 = r'a*\ba*'
    # fan_content1, num_constraints1 = translator.generate_ebnf_grammar_with_constraints(regex1)
    
    # print(f"Generated Fandango content for regex: {regex1}\n")
    # print(fan_content1)
    # print(f"\nNumber of constraints generated: {num_constraints1}")

    pass