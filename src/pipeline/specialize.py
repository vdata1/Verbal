r"""Stage 2 -- specializer: base ``.fan`` + descriptor -> ``<api>.fan``.

Realizes the descriptor's declarative knobs (``min_matches``, ``filler_between``,
``groups_must_participate``, ``extra_constraints``/``extra_helpers``) as uniform
grammar + constraint edits. The core here NEVER branches on ``descriptor.api`` or
on a regex id -- every difference between APIs flows through descriptor *data*,
and every regex is treated by the same code path.

Realization (syntax validated by fuzzing before this module
was written):

- ``min_matches == 1`` -> no grammar rewrite; base already yields one match.
- ``min_matches == k > 1`` -> rename the base ``<start>`` body to a match unit
  ``<m>`` and add ``<start> ::= <pad> (<m> <pad>){k,K}`` plus ``<pad> ::= "<c>"``.
  ``K`` = ``config.matchall_k`` bounds string size (``*``/``{2,}`` overshoot to
  medians 5-20). The structural ``{k,K}`` lower bound realizes the count IN THE
  GRAMMAR (rather than via a pure count constraint), which the spike validated as
  reliable; the fixed-exact variant is the flaky one and is deliberately avoided.
- ``<pad>`` -- there is NO universal pad. The correct pad is a character the regex
  cannot match; we pick the first ``config.pad_candidates`` entry the regex can't
  match (uniform list + rule for every regex). Post-counting in Stage 3 is the
  real correctness guarantee and we do NOT hard-filter by an engine match count.
- Degenerate regex (matches every candidate -> no non-matching pad exists, e.g.
  ``[\s\S]+``): a >=2-separated-match string is impossible. Human decision
  accept 1 match. The rewrite is skipped and RECORDED -- a uniform
  classification by the same test for every regex, not per-instance special-casing.
- ``groups_must_participate`` -> append ``where <rN> != ""`` for each capture-group
  rule (from the base spec's ``capture_group_rules`` meta).
- ``required_flags`` -- harness-side only (Stage 3 ``new RegExp(pattern, flags)``);
  recorded here in the result, not in the ``.fan``.
"""

from __future__ import annotations

import json
import re as _re
from dataclasses import dataclass

from regex_fandango_transpiler import normalize_js_regex
from pipeline.api_descriptors import ApiDescriptor
from pipeline.base_spec import CAPTURE_GROUP_META
from pipeline.config import Config, provenance_header_lines
from pipeline.regex_facts import RegexFacts, analyze as analyze_regex, effective_flags
import paths

# Section markers emitted verbatim by the transpiler (make_fan_file_content).
_GRAMMAR_MARK = "# Grammar:"
_CONSTRAINTS_MARK = "# Constraints:"
_GENERATORS_MARK = "# Generators:"

MATCH_UNIT = "<m>"
PAD_RULE = "<pad>"


@dataclass(frozen=True)
class SpecializationResult:
    api: str
    fan_content: str
    pad: str | None            # chosen pad char; None if min_matches==1 or single-match fallback
    degenerate: bool           # True iff >=2 requested but regex matches ALL pad candidates
    anchored_single_match: bool  # True iff >=2 requested but the regex can match at most once
    flags: str                 # effective harness flags (API required UNION regex requires)
    reason: str                # note for the run record (always populated)


def _split_sections(base_fan: str) -> tuple[str, str, str, str]:
    """Split base ``.fan`` into (prelude, grammar, constraints, generators).

    Raises (fail loud) if any of the fixed section markers is missing -- that
    means the transpiler output format drifted and every downstream edit is unsafe.
    """
    for mark in (_GRAMMAR_MARK, _CONSTRAINTS_MARK, _GENERATORS_MARK):
        if mark not in base_fan:
            raise ValueError(f"base .fan missing section marker {mark!r}; format drift?")
    prelude, rest = base_fan.split(_GRAMMAR_MARK, 1)
    grammar, rest = rest.split(_CONSTRAINTS_MARK, 1)
    constraints, generators = rest.split(_GENERATORS_MARK, 1)
    return prelude, grammar, constraints, generators


def _parse_capture_group_rules(prelude: str) -> tuple[str, ...]:
    """Read the capture-group rule names the base spec recorded in its meta line."""
    for line in prelude.splitlines():
        if line.startswith(CAPTURE_GROUP_META):
            payload = line[len(CAPTURE_GROUP_META):].strip()
            return tuple(r for r in payload.split(",") if r)
    return ()


def _preserved_prelude_lines(prelude: str) -> list[str]:
    """Keep only the functional prelude bits: ``import fandango`` and ``# regex:``.

    The base provenance header is dropped and re-emitted fresh for this stage; the
    capture-group meta is re-emitted by the caller.
    """
    kept = []
    for line in prelude.splitlines():
        s = line.strip()
        if s.startswith("import ") or s.startswith("# regex:"):
            kept.append(line.rstrip())
    return kept


def select_pad(pattern: str, candidates: tuple[str, ...]) -> str | None:
    r"""First candidate the regex cannot match, or None (degenerate: matches all).

    Normalize via ``normalize_js_regex`` before compiling under Python ``re``: the
    transpiler accepts JS escapes (``\\u{...}``, ``\A``/``\Z``/``\z``) that raw ``re``
    reads differently or rejects, so compiling the un-normalized pattern would crash
    or disagree. After normalization it compiles under ``re`` exactly as it did under
    the transpiler's ``sre_parse``.
    """
    compiled = _re.compile(normalize_js_regex(pattern))
    for c in candidates:
        if compiled.search(c) is None:
            return c
    return None


def _rewrite_start_for_repetition(grammar: str, pad: str, k: int, upper: int) -> str:
    """Rename ``<start>`` body to ``<m>`` and add repeated-match ``<start>``+``<pad>``."""
    lines = grammar.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("<start> ::="):
            start_idx = i
            break
    if start_idx is None:
        raise ValueError("grammar has no `<start> ::=` production to rewrite")

    # Rename LHS only: `<start> ::= BODY` -> `<m> ::= BODY`.
    lines[start_idx] = lines[start_idx].replace("<start> ::=", f"{MATCH_UNIT} ::=", 1)

    new_rules = [
        f"<start> ::= {PAD_RULE} ({MATCH_UNIT} {PAD_RULE}){{{k},{upper}}}",
        f"{PAD_RULE} ::= {json.dumps(pad)}",
    ]
    lines[start_idx:start_idx] = new_rules
    return "\n".join(lines)


def specialize(base_fan: str, pattern: str, descriptor: ApiDescriptor, config: Config,
               facts: RegexFacts | None = None) -> SpecializationResult:
    """Produce the specialized ``<api>.fan`` content for one regex + descriptor.

    `facts` is the Stage-1 :class:`RegexFacts`; if omitted it is derived from
    `pattern` (convenient for tests / standalone calls). Passing the precomputed
    facts avoids re-parsing and keeps a single source of truth for the run record.
    """
    if descriptor.min_matches < 1:
        raise ValueError(f"min_matches must be >= 1, got {descriptor.min_matches}")
    if descriptor.min_matches > config.matchall_k:
        raise ValueError(
            f"min_matches ({descriptor.min_matches}) exceeds matchall_k "
            f"({config.matchall_k}); raise matchall_k in config"
        )
    if facts is None:
        facts = analyze_regex(pattern)

    prelude, grammar, constraints, generators = _split_sections(base_fan)
    capture_group_rules = _parse_capture_group_rules(prelude)

    pad: str | None = None
    degenerate = False
    anchored_single_match = False
    reasons: list[str] = []

    # --- min_matches realization -------------------------------------------
    if descriptor.min_matches > 1 and facts.anchored_single_match:
        # Fully-anchored regex: can match at most once, so the >=2-match rewrite
        # would emit padded copies that never match. Same
        # uniform fallback as `degenerate` below (human-approved: accept 1 match),
        # but recorded as its OWN fact so the run record distinguishes the two.
        anchored_single_match = True
        reasons.append(
            f"anchored-single-match: /{pattern}/ is anchored (matches at most once); "
            f"accepting 1 match (>=2 impossible)"
        )
    elif descriptor.min_matches > 1:
        pad = select_pad(pattern, config.pad_candidates)
        if pad is None:
            # Degenerate: regex matches every candidate -> no separating pad exists.
            # Human-approved: accept 1 match; emit base grammar unchanged.
            degenerate = True
            reasons.append(
                f"degenerate: no non-matching pad in candidates for /{pattern}/; "
                f"accepting 1 match (>=2 impossible)"
            )
        else:
            grammar = _rewrite_start_for_repetition(
                grammar, pad, descriptor.min_matches, config.matchall_k
            )
            reasons.append(
                f"repeated-match rewrite k={descriptor.min_matches} "
                f"K={config.matchall_k} pad=U+{ord(pad):04X}"
            )
    else:
        reasons.append("single-match base (min_matches=1)")

    # --- constraint additions ----------------------------------------------
    added_constraints: list[str] = []
    if descriptor.groups_must_participate:
        added_constraints.extend(f'where {rule} != ""' for rule in capture_group_rules)
        if capture_group_rules:
            reasons.append(f"groups_must_participate: {len(capture_group_rules)} group(s)")
    added_constraints.extend(descriptor.extra_constraints)

    if added_constraints:
        constraints = (
            constraints.rstrip()
            + "\n\n# Specialization constraints ("
            + descriptor.api
            + ")\n\n"
            + "\n".join(added_constraints)
            + "\n"
        )

    # --- generator/helper additions -----------------------------------------
    if descriptor.extra_helpers:
        generators = generators.rstrip() + "\n\n" + "\n\n".join(descriptor.extra_helpers) + "\n"

    # Effective harness flags: the API's mechanical flags UNION the regex's proven
    # required flags (e.g. matchAll `g` + a `\u{}` pattern's `u`). Recorded here and
    # used by Stage 3 harness synthesis so the engine reads the source the same way
    # the grammar generated it.
    flags = effective_flags(descriptor.required_flags, facts.requires_flags)
    if facts.requires_flags:
        reasons.append(f"requires_flags={''.join(sorted(facts.requires_flags))} "
                       f"-> effective flags '{flags or '(none)'}'")

    # --- reassemble ----------------------------------------------------------
    header = provenance_header_lines(
        config,
        stage="specialize",
        api=descriptor.api,
        api_required_flags=descriptor.required_flags or "(none)",
        regex_requires_flags="".join(sorted(facts.requires_flags)) or "(none)",
        effective_flags=flags or "(none)",
        pad=(f"U+{ord(pad):04X}" if pad is not None else "(none)"),
        degenerate=degenerate,
        anchored_single_match=anchored_single_match,
    )
    header.append(CAPTURE_GROUP_META + ",".join(capture_group_rules))
    prelude_kept = _preserved_prelude_lines(prelude)

    parts = ["\n".join(header)]
    if prelude_kept:
        parts.append("\n".join(prelude_kept))
    parts.append(_GRAMMAR_MARK + grammar.rstrip() + "\n")
    parts.append(_CONSTRAINTS_MARK + constraints.rstrip() + "\n")
    parts.append(_GENERATORS_MARK + generators.rstrip() + "\n")
    fan_content = "\n\n".join(parts) + "\n"

    return SpecializationResult(
        api=descriptor.api,
        fan_content=fan_content,
        pad=pad,
        degenerate=degenerate,
        anchored_single_match=anchored_single_match,
        flags=flags,
        reason="; ".join(reasons),
    )


def write_specialization(rid: str, descriptor: ApiDescriptor, pattern: str, config: Config,
                         facts: RegexFacts | None = None) -> SpecializationResult:
    """Read ``results/<rid>/base.fan``, specialize for `descriptor`, write ``<api>.fan``."""
    base_path = paths.base_fan_path(rid)
    with open(base_path, "r") as f:
        base_fan = f.read()
    result = specialize(base_fan, pattern, descriptor, config, facts)
    out_path = paths.api_fan_path(rid, descriptor.api)
    with open(out_path, "w") as f:
        f.write(result.fan_content)
    return result
