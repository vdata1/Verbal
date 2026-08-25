"""Stage 1 -- base spec builder.

Turns a regex into ONE clean, mutation-free base ``.fan`` (grammar + the
constraints the transpiler emits for lookaround / backreferences). This is the
starting point every per-API specialization builds on; it must not bake in any
API-specific or mutation behavior (settled design 2026-07-06).

Thin wrapper over the reused transpiler core
(``regex_fandango_transpiler.RegexToFandangoTranslator``). The transpiler owns
all regex->grammar logic; this module only drives it and attaches provenance.
"""

from __future__ import annotations

from regex_fandango_transpiler import RegexToFandangoTranslator
from pipeline.config import Config, provenance_header_lines
from pipeline.regex_facts import RegexFacts, analyze as analyze_regex
import paths


CAPTURE_GROUP_META = "# meta: capture_group_rules="
REGEX_FACTS_META = "# meta: regex_facts="


def build_base_spec(regex_pattern: str) -> tuple[str, int, tuple[str, ...], RegexFacts]:
    """Transpile a regex into base ``.fan`` content + metadata.

    Returns ``(fan_content, num_constraints, capture_group_rules, facts)`` where
    ``capture_group_rules`` is the grammar rule name backing each numbered capture
    group (ordered by group number), pulled from the transpiler's own
    ``group_to_rule`` map -- the specializer needs it to realize
    ``groups_must_participate`` without re-parsing or guessing from grammar text --
    and ``facts`` is the per-regex :class:`RegexFacts` analysis (anchoring +
    required flags), computed ONCE here (Stage 1) and threaded downstream.

    Pure: no filesystem, no mutation. Raises (fail loud) on a non-string input
    or an un-parseable regex -- the transpiler raises ``ValueError`` on the latter.
    """
    if not isinstance(regex_pattern, str):
        raise TypeError(
            f"regex_pattern must be str, got {type(regex_pattern).__name__}"
        )
    translator = RegexToFandangoTranslator()
    fan_content, num_constraints = translator.generate_ebnf_grammar_with_constraints(
        regex_pattern
    )
    group_to_rule = translator.ebnf_visitor.group_to_rule
    capture_group_rules = tuple(group_to_rule[g] for g in sorted(group_to_rule))
    # Safe now: the transpiler parsed the pattern above, so analyze() re-parses a
    # pattern already known to parse.
    facts = analyze_regex(regex_pattern)
    return fan_content, num_constraints, capture_group_rules, facts


def write_base_spec(regex_pattern: str, rid: str, config: Config) -> tuple[str, int, tuple[str, ...], RegexFacts]:
    """Build the base ``.fan`` for `regex_pattern` and write it to its artifact path.

    Returns ``(base_fan_path, num_constraints, capture_group_rules, facts)``. The
    written file carries a provenance header plus ``capture_group_rules`` and
    ``regex_facts`` meta comments so it is both traceable (code+config+seed+corpus)
    and self-describing for Stage 2.
    """
    fan_content, num_constraints, capture_group_rules, facts = build_base_spec(regex_pattern)
    header = provenance_header_lines(config, stage="base_spec", regex_id=rid)
    header.append(CAPTURE_GROUP_META + ",".join(capture_group_rules))
    header.append(REGEX_FACTS_META + facts.to_meta())
    content = "\n".join(header) + "\n\n" + fan_content

    paths.ensure_regex_dir(rid)
    out_path = paths.base_fan_path(rid)
    with open(out_path, "w") as f:
        f.write(content)
    return out_path, num_constraints, capture_group_rules, facts
