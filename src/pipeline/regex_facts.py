r"""Stage 1 analysis -- per-regex *facts* derived once from the pattern.

These are properties of the regex itself (not of any API), computed a single time
in the base-spec stage and threaded to specialization + harness synthesis so no
downstream stage has to re-derive them (and so they are recorded as first-class,
machine-readable metadata rather than folded into a bool). See CLAUDE.md
("configuration over code", "separate testable units").

Two facts today, both structural (from ``sre_parse`` -- the same parser the
transpiler uses -- so a ``^``/``$`` appearing mid-pattern or in one branch is
never mis-read by a string heuristic):

- ``anchored_single_match`` -- the regex can match at most once in any string
  (every top-level alternative is anchored to the string start OR every one to the
  end). Used by the specializer to skip the >=2-match rewrite for matchAll
  (otherwise it emits padded copies that never match -- Bug A, 2026-07-07 scan).

- ``requires_flags`` -- the JS flags the pattern *requires* to be matchable /
  meaningful AT ALL, as opposed to ``ApiDescriptor.required_flags`` (the flags an
  API mechanically needs, e.g. matchAll -> ``g``). The container is the full JS
  flag alphabet (``gimsuy``); the detectors below populate what they can *prove*:
    * ``m`` (multiline) -- an ``m``-sensitive anchor (``^``/``$``, i.e. Python
      ``AT_BEGINNING``/``AT_END``; NOT ``\A``/``\Z`` which ``m`` does not affect)
      nested inside a repetition forced to run >=2 times (e.g. ``(^...\n){2,}``):
      the repeated anchor needs the line boundaries ``m`` supplies. (An internal
      ``$`` merely *followed by* required content is NOT rescued by ``m`` -- it is
      unsatisfiable; see ``unsatisfiable_internal_anchor`` below.)
    * ``u`` (unicode) -- the pattern uses ``u``-only syntax (``\u{...}`` braced
      code-point escapes, ``\p{...}``/``\P{...}`` property escapes). The transpiler
      reads ``\u{...}`` as the code point (ES6/u semantics), so the engine harness
      MUST carry ``u`` or it would read the same source as literal text and disagree
      with the generated grammar.
  The remaining flags (``i``/``s``/``y``) are never *required* for a match to exist
  -- they only widen behavior -- so they are left for synthesis-time flag variation,
  not detected here. The field can still carry them (full-set container by design).

- ``unsatisfiable_internal_anchor`` -- a REQUIRED, non-alternated ``$``/``^`` that
  pins a line boundary exactly where a non-newline literal is required, so the regex
  matches NOTHING in JS even with ``m`` (e.g. ``_$foreign_id$`` -- an unexpanded
  ``$var`` template). The driver records such a regex as its own outcome instead of
  generating strings that can never match. Sound/conservative (see the function).

Detection is deliberately SOUND-but-incomplete: a missed requirement just leaves a
non-matching string (no worse than before); a *false* requirement would wrongly add
a flag to every harness for that regex, so the rules only fire when structurally
certain.
"""

from __future__ import annotations

import json
import sre_parse
from dataclasses import dataclass, field

from regex_fandango_transpiler import normalize_js_regex

# The JS regex flag alphabet in canonical `.flags`-getter order (spec order, `d`
# first). `effective_flags`/`variant_flag_sets` join present flags in THIS order, so a
# flag absent here is silently dropped from the harness flag string -- keep it complete.
# `requires_flags` is a subset; the container is general even though only `m`/`u` are
# required today. `v` (unicodeSets, ES2024) is a tested VARIANT but is never *required*
# -- see `_canonical_flags` for why it can never simply be unioned in.
ALL_JS_FLAGS = ("d", "g", "i", "m", "s", "u", "v", "y")


def _canonical_flags(present: set) -> str:
    """Order a flag set canonically, resolving the one pair that cannot coexist.

    ``u`` and ``v`` together are a ``SyntaxError`` on every engine, so a set containing
    both is not a harness -- it is a guaranteed throw. ``v`` WINS, because unicodeSets
    mode is a strict superset of unicode mode: everything ``u`` guarantees, ``v`` also
    guarantees (plus set notation, ``\\q{...}``, properties-of-strings). Dropping ``u``
    therefore never weakens a regex that required it.

    This matters far more than it looks. ``u`` is required exactly for ``\\p{...}`` /
    ``\\u{...}`` patterns -- which are precisely the patterns ``v`` is interesting on
    (we already know bun fails ``/\\p{Lu}/vi``). A plain union would hand every one of
    them ``uv`` and turn the entire ``v`` axis into a SyntaxError that all three engines
    agree on: maximum cost, zero signal, and it would look like coverage.
    """
    if "v" in present:
        present = present - {"u"}
    return "".join(f for f in ALL_JS_FLAGS if f in present)


def effective_flags(api_required: str, regex_requires) -> str:
    """The flags a harness must carry: the API's mechanical flags (e.g. matchAll's
    ``g``) UNION the regex's required flags, in canonical ``.flags``-getter order so the
    string is deterministic across engines/runs."""
    return _canonical_flags(set(api_required) | set(regex_requires))


def js_construction_flags(pattern: str) -> str:
    r"""The construction-affecting JS flags a harness will carry for `pattern`.

    Only ``u``/``v`` change whether a pattern *constructs* -- they tighten escape
    strictness; ``g``/``i``/``m``/``s``/``y`` never affect construction validity. ``u``
    is required exactly when the pattern uses ``\u{...}`` or ``\p{...}``
    (:func:`_requires_u`). So the validity gate must test a pattern under ``u`` iff it
    requires it: otherwise the gate admits it flagless while the specializer runs it
    under ``/u``, where it throws ``SyntaxError`` on every engine and is silently
    recorded ``ok`` (EXPERIMENT_GAPS G1). This is the ``u``-only slice of
    :func:`effective_flags` -- the only part that gates construction.

    ``v`` is deliberately NOT consulted, even though it gates construction too and is
    now a tested variant. ``v`` is only ever OPTIONAL, and it is *stricter* than ``u``
    (it reserves more punctuation inside classes), so gating on it would exclude
    patterns that are perfectly valid under the flags they actually require -- turning
    G1's fix into an over-correction that shrinks the corpus. A ``v`` variant that
    cannot construct is a per-harness ``SyntaxError``, i.e. a comparable outcome the
    engines must agree on, which is exactly the signal we want from that axis."""
    return "u" if _requires_u(pattern) else ""


def variant_flag_sets(api_required: str, regex_requires, variant_mods) -> list:
    """The ordered, de-duplicated list of flag strings to synthesize harnesses for.

    The mandatory base (``effective_flags``) is ALWAYS first, so the required-only
    variant is tested even if the config omits ``""``. Each configured modifier is
    UNIONed onto the base; required flags are never dropped (a modifier can only add
    optional flags) -- with the single exception of ``u`` under a ``v`` modifier, where
    ``v`` subsumes it rather than colliding with it (see :func:`_canonical_flags`).
    Canonical ``.flags``-getter order + de-dup so identical effective sets collapse to
    one variant regardless of how they were requested.
    """
    base = set(api_required) | set(regex_requires)
    out: list = []
    seen: set = set()
    for mod in [""] + list(variant_mods):
        v = _canonical_flags(base | set(mod))
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out

# Anchors, split by whether the `m` flag changes their meaning.
_M_SENSITIVE_BEGIN = (sre_parse.AT_BEGINNING,)          # `^`
_M_SENSITIVE_END = (sre_parse.AT_END,)                  # `$`
# `\A`/`\Z` are absolute (m-insensitive); still count for single-match anchoring.
_AT_BEGIN = (sre_parse.AT_BEGINNING, sre_parse.AT_BEGINNING_STRING)
_AT_END = (sre_parse.AT_END, sre_parse.AT_END_STRING)

@dataclass(frozen=True)
class RegexFacts:
    """First-class, per-regex analysis facts (see module docstring)."""
    anchored_single_match: bool = False
    requires_flags: frozenset = field(default_factory=frozenset)
    # A required `$`/`^` that pins a line boundary where a non-newline literal is
    # required -> the regex matches nothing (see _unsatisfiable_internal_anchor).
    unsatisfiable_internal_anchor: bool = False

    def to_meta(self) -> str:
        """Serialize to the JSON payload stored in the base ``.fan`` meta line."""
        return json.dumps(
            {"anchored_single_match": self.anchored_single_match,
             "requires_flags": sorted(self.requires_flags),
             "unsatisfiable_internal_anchor": self.unsatisfiable_internal_anchor},
            sort_keys=True, ensure_ascii=True,
        )

    @classmethod
    def from_meta(cls, payload: str) -> "RegexFacts":
        d = json.loads(payload)
        return cls(
            anchored_single_match=bool(d.get("anchored_single_match", False)),
            requires_flags=frozenset(d.get("requires_flags", ())),
            unsatisfiable_internal_anchor=bool(d.get("unsatisfiable_internal_anchor", False)),
        )


# --- single-match anchoring (moved from specialize.py) -----------------------

def _top_level_branches(parsed) -> list:
    """The top-level alternatives as a list of op-sequences (one entry if no `|`)."""
    items = list(parsed)
    if len(items) == 1 and items[0][0] == sre_parse.BRANCH:
        _, (_, subs) = items[0]
        return [list(s) for s in subs]
    return [items]


def _leading_op(seq):
    """First op of `seq`, recursing into a leading SUBPATTERN (e.g. `(^a)b`)."""
    if not seq:
        return None
    op, av = seq[0]
    if op == sre_parse.SUBPATTERN:
        return _leading_op(list(av[-1]))
    return (op, av)


def _trailing_op(seq):
    """Last op of `seq`, recursing into a trailing SUBPATTERN (e.g. `a(b$)`)."""
    if not seq:
        return None
    op, av = seq[-1]
    if op == sre_parse.SUBPATTERN:
        return _trailing_op(list(av[-1]))
    return (op, av)


def _is_anchored_single_match(parsed) -> bool:
    branches = _top_level_branches(parsed)

    def _starts_anchored(seq) -> bool:
        lead = _leading_op(seq)
        return lead is not None and lead[0] == sre_parse.AT and lead[1] in _AT_BEGIN

    def _ends_anchored(seq) -> bool:
        trail = _trailing_op(seq)
        return trail is not None and trail[0] == sre_parse.AT and trail[1] in _AT_END

    return (all(_starts_anchored(b) for b in branches)
            or all(_ends_anchored(b) for b in branches))


# --- requires-`m` detection --------------------------------------------------

def _anchor_in_forced_repeat(seq, under_min2: bool) -> bool:
    """True if an m-sensitive anchor is nested inside a repeat forced to run >=2x."""
    for op, av in seq:
        if op == sre_parse.AT and av in (_M_SENSITIVE_BEGIN + _M_SENSITIVE_END):
            if under_min2:
                return True
        elif op in (sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT):
            mn, _mx, sub = av
            child = under_min2 or (isinstance(mn, int) and mn >= 2)
            if _anchor_in_forced_repeat(list(sub), child):
                return True
        elif op == sre_parse.SUBPATTERN:
            if _anchor_in_forced_repeat(list(av[-1]), under_min2):
                return True
        elif op == sre_parse.BRANCH:
            if any(_anchor_in_forced_repeat(list(b), under_min2) for b in av[1]):
                return True
        elif op in (sre_parse.ASSERT, sre_parse.ASSERT_NOT):
            if _anchor_in_forced_repeat(list(av[1]), under_min2):
                return True
    return False


# Flatten-token kinds for internal-anchor adjacency. We collapse the parse tree into
# a linear sequence of the REQUIRED concatenation so a `$`/`^` and its neighbour are
# visible even ACROSS subpattern boundaries (e.g. `(...$)\n(^...)`).
_FLAT_NL = ("NL",)        # a REQUIRED newline literal (the line boundary `m` supplies)
_FLAT_CHAR = ("CHAR",)    # any other GUARANTEED single char (literal / class / `.`)
_FLAT_EMPTY = ("EMPTY",)  # a possibly-empty element (min==0 repeat, lookaround, \b, backref)


def _flatten_required(seq) -> list:
    r"""Linearize `seq` into adjacency tokens, splicing required subpatterns and
    min>=1 repeats (ONE copy -- enough to see a `$`/`^` and its literal neighbour) so
    cross-boundary adjacency like `(a$)\n(^b)` becomes visible. Optional repeats,
    lookarounds, word boundaries and backreferences become opaque ``EMPTY`` markers
    that can never masquerade as a guaranteed char; a BRANCH keeps its alternatives
    for a separate all-branches check."""
    out = []
    for op, av in seq:
        if op == sre_parse.AT:
            out.append(("AT", av))
        elif op == sre_parse.LITERAL:
            out.append(_FLAT_NL if av == 0x0A else _FLAT_CHAR)
        elif op in (sre_parse.IN, sre_parse.ANY, sre_parse.CATEGORY, sre_parse.NOT_LITERAL):
            out.append(_FLAT_CHAR)
        elif op == sre_parse.SUBPATTERN:
            out.extend(_flatten_required(list(av[-1])))
        elif op in (sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT):
            mn, _mx, sub = av
            if isinstance(mn, int) and mn >= 1:
                out.extend(_flatten_required(list(sub)))
            else:
                out.append(_FLAT_EMPTY)
        elif op == sre_parse.BRANCH:
            out.append(("BRANCH", av[1]))
        else:
            # GROUPREF (may match empty), ASSERT / ASSERT_NOT, AT_BOUNDARY, etc.:
            # not a guaranteed char -> opaque, so it never reads as a false `CHAR`.
            out.append(_FLAT_EMPTY)
    return out


def _requires_m_via_newline(seq) -> bool:
    r"""Sound `m` detection for an m-sensitive anchor pinned against a REQUIRED newline
    (the cross-boundary case ``_anchor_in_forced_repeat`` cannot see):

      * ``$`` immediately followed by a required ``\n`` that itself has guaranteed
        content after it: without ``m``, ``$`` matches only at end-of-string or before
        the FINAL ``\n``; a non-final required ``\n`` forces ``m`` (regex_246
        ``(^.*$)\n(^ +return)``).
      * ``^`` immediately preceded by a required ``\n``: ``^`` then sits at position
        >=1 (never string-start), so only ``m`` (post-newline ``^``) can satisfy it.

    A BRANCH forces ``m`` only if EVERY alternative does. No false positives: optional,
    branch, and backref neighbours are opaque, so a ``$``/``^`` that could still sit at
    a genuine string boundary is never flagged.
    """
    flat = _flatten_required(list(seq))
    n = len(flat)
    for i, tok in enumerate(flat):
        if tok == ("AT", sre_parse.AT_END):
            if (i + 1 < n and flat[i + 1] == _FLAT_NL
                    and any(flat[j] in (_FLAT_NL, _FLAT_CHAR) for j in range(i + 2, n))):
                return True
        elif tok == ("AT", sre_parse.AT_BEGINNING):
            if i - 1 >= 0 and flat[i - 1] == _FLAT_NL:
                return True
    for tok in flat:
        if tok[0] == "BRANCH":
            subs = tok[1]
            if subs and all(_requires_m_via_newline(list(b)) for b in subs):
                return True
    return False


def _requires_m(parsed) -> bool:
    # Two SOUND paths to a required `m`:
    #  (1) an m-sensitive anchor inside a repeat forced to run >=2 times, which can
    #      only be satisfied at the line boundaries `m` provides (e.g. regex_85
    #      `(^\s*>.*\n){2,}`);
    #  (2) a `$`/`^` pinned against a required newline that no string boundary can
    #      supply (e.g. regex_246 `(^.*$)\n(^ +return)`) -- see _requires_m_via_newline.
    return (_anchor_in_forced_repeat(list(parsed), under_min2=False)
            or _requires_m_via_newline(list(parsed)))


# --- unsatisfiable internal anchor -------------------------------------------

def _unsatisfiable_internal_anchor(seq) -> bool:
    r"""True if a REQUIRED, non-alternated `$`/`^` pins a line boundary exactly where
    a non-newline literal is required -- so the regex matches NOTHING (in JS, even
    with `m`). E.g. `_$foreign_id$`: the first `$` demands end-of-line, but the next
    required char is literal `f`, which can never be that boundary. (These are
    usually unexpanded template variables, e.g. `$pattern`/`$k`.)

    Sound -- no false positives: recurse ONLY into required paths (bare subpatterns,
    repeats with min>=1); NOT into optional (min==0) repeats. Only flags a `$`/`^`
    whose IMMEDIATELY adjacent required element in the SAME concatenation is a LITERAL
    other than `\n`, which cannot supply the required line boundary. Conservative: it
    may miss some unsatisfiable regexes, but never flags a satisfiable one.

    A BRANCH is unsatisfiable only when EVERY alternative is (a single satisfiable
    alternative rescues the whole) -- so recursion into BRANCH uses ``all(...)``. This
    catches all-branch templates like ``^ @?$me_nick ... | ... $me_nick ... | ...``
    (regex_2068, an unexpanded ``$me_nick``) while keeping ``(a$b)|c`` unflagged.
    """
    _NL = 0x0A
    for i, (op, av) in enumerate(seq):
        if op == sre_parse.AT and av in _M_SENSITIVE_END and i + 1 < len(seq):
            nop, nav = seq[i + 1]
            if nop == sre_parse.LITERAL and nav != _NL:
                return True
        if op == sre_parse.AT and av in _M_SENSITIVE_BEGIN and i - 1 >= 0:
            pop, pav = seq[i - 1]
            if pop == sre_parse.LITERAL and pav != _NL:
                return True
        if op == sre_parse.SUBPATTERN:
            if _unsatisfiable_internal_anchor(list(av[-1])):
                return True
        elif op in (sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT):
            mn, _mx, sub = av
            if isinstance(mn, int) and mn >= 1 and _unsatisfiable_internal_anchor(list(sub)):
                return True
        elif op == sre_parse.BRANCH:
            subs = av[1]
            if subs and all(_unsatisfiable_internal_anchor(list(b)) for b in subs):
                return True
    return False


# --- requires-`u` detection (syntactic; on the RAW pattern) ------------------

def _requires_u(pattern: str) -> bool:
    r"""True if the pattern uses ``u``-only syntax: ``\u{...}``, ``\p{...}``,
    ``\P{...}``. Scans the raw source, counting backslashes so an escaped
    backslash (``\\u{``) is not mistaken for the escape."""
    i, n = 0, len(pattern)
    while i < n:
        if pattern[i] != "\\":
            i += 1
            continue
        # Count the run of backslashes; an even run is literal backslashes.
        j = i
        while j < n and pattern[j] == "\\":
            j += 1
        run = j - i
        if run % 2 == 1 and j < n:
            nxt = pattern[j]
            if nxt == "u" and j + 1 < n and pattern[j + 1] == "{":
                return True
            if nxt in ("p", "P") and j + 1 < n and pattern[j + 1] == "{":
                return True
        i = j + 1 if run % 2 == 1 else j
    return False


def analyze(pattern: str) -> RegexFacts:
    r"""Compute :class:`RegexFacts` for `pattern`. Pure; parses via ``sre_parse``.

    Assumes `pattern` already produced a base spec (so it parses); callers that may
    pass an un-parseable pattern should guard. Uses the same ``normalize_js_regex``
    normalization the transpiler applies -- so anchoring/`m` detection see JS
    semantics (``\A``/``\Z``/``\z`` are literal letters, not anchors). `_requires_u`
    scans the RAW pattern (it must see ``\u{`` before rewriting).
    """
    parsed = sre_parse.parse(normalize_js_regex(pattern))
    flags = set()
    if _requires_m(parsed):
        flags.add("m")
    if _requires_u(pattern):
        flags.add("u")
    return RegexFacts(
        anchored_single_match=_is_anchored_single_match(parsed),
        requires_flags=frozenset(flags),
        unsatisfiable_internal_anchor=_unsatisfiable_internal_anchor(list(parsed)),
    )
