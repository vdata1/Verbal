"""Central filesystem layout for the Verbal pipeline.

Single source of truth for every input/output location. All paths are resolved
from the project root (derived from this file's location) rather than from the
current working directory, so the pipeline produces the same layout no matter
where it is launched from. See CLAUDE.md ("configuration over code") -- do not
reintroduce scattered CWD-relative path constants in the individual modules.

Layout:
    <root>/data      inputs (regex corpora), tracked in git
    <root>/src       pipeline code + unit_test_templates
    <root>/results   all generated outputs, gitignored
"""

import os

# This file lives at <root>/src/paths.py, so the root is two levels up.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Inputs (tracked in git) -------------------------------------------------
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
REGEX_CORPUS = os.path.join(DATA_DIR, "uniq-regexes-8.json")

# --- Code-adjacent assets ----------------------------------------------------
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
UNIT_TEST_TEMPLATES_DIR = os.path.join(SRC_DIR, "unit_test_templates")
PIPELINE_DIR = os.path.join(SRC_DIR, "pipeline")
# Node script used as the reference JS-regex validity gate (see pipeline/js_regex.py).
JS_REGEX_PROBE = os.path.join(PIPELINE_DIR, "js_regex_probe.js")

# --- Outputs (gitignored, created on demand) ---------------------------------
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
GENERATED_GRAMMARS_DIR = os.path.join(RESULTS_DIR, "generated_grammars")
GENERATED_TEST_INPUTS_DIR = os.path.join(RESULTS_DIR, "generated_test_inputs")
GENERATED_UNIT_TESTS_DIR = os.path.join(RESULTS_DIR, "generated_unit_tests")
DIFF_TEST_RESULTS_DIR = os.path.join(RESULTS_DIR, "diff_test_results")
GENERATION_RECORD = os.path.join(RESULTS_DIR, "generation_record.json")

# --- Config (versioned experiment parameters) --------------------------------
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
DEFAULT_CONFIG = os.path.join(CONFIG_DIR, "default.yaml")


# --- New pipeline: per-regex artifact layout ---------------------------------
# Every artifact for a regex lives under results/<regex_id>/, so all stages are
# joinable by id and there is room for a mutations/ subtree later. See the
# settled pipeline design (2026-07-06).
#
#   results/<regex_id>/base.fan               Stage 1 output (mutation-free)
#   results/<regex_id>/<api>.fan              Stage 2 output (specialized)
#   results/<regex_id>/<api>.strings.jsonl    Stage 3 generated strings
#   results/<regex_id>/<api>__<n>.js          Stage 3 synthesized harness
#   results/<regex_id>/<api>.diff.json        eval cross-engine diff
#
# regex_id scheme: `regex_<n>` where n is the 0-based line index of the regex in
# the corpus JSONL. Chosen (over a content hash) to match the existing scheme and
# because the corpus is a fixed, ordered file consumed via a deterministic slice,
# so positional ids are stable and human-legible. Documented per the handoff.


def regex_id(index: int) -> str:
    """Stable id for the regex at 0-based corpus line `index`."""
    if index < 0:
        raise ValueError(f"corpus index must be >= 0, got {index}")
    return f"regex_{index}"


def regex_dir(rid: str) -> str:
    return os.path.join(RESULTS_DIR, rid)


def base_fan_path(rid: str) -> str:
    return os.path.join(regex_dir(rid), "base.fan")


def api_fan_path(rid: str, api: str) -> str:
    return os.path.join(regex_dir(rid), f"{api}.fan")


def api_strings_path(rid: str, api: str) -> str:
    return os.path.join(regex_dir(rid), f"{api}.strings.jsonl")


def harness_flag_tag(flags: str) -> str:
    """Filename-safe tag for a harness's flag set (``""`` -> ``none``)."""
    return flags if flags else "none"


def api_harness_path(rid: str, api: str, n: int, flags: str) -> str:
    # results/<rid>/<api>__<n>__<flagtag>.js  -- one harness per (string, flag set).
    return os.path.join(regex_dir(rid), f"{api}__{n}__{harness_flag_tag(flags)}.js")


def api_diff_path(rid: str, api: str) -> str:
    return os.path.join(regex_dir(rid), f"{api}.diff.json")


# --- Per-window run artifacts ------------------------------------------------
# run_record and eval_headline describe ONE corpus window [start, end). They are
# named for that window rather than written to a fixed path: a fixed name means a
# second chunk silently overwrites the first one's record, which loses the earlier
# chunk's outcomes (the artifacts survive, but nothing records that they are
# evaluable) and leaves a headline that describes a narrower window than the
# results directory it sits in. The window is in the filename so chunks coexist and
# every file says which rows it covers.


def window_tag(start: int, end: int | None) -> str:
    """Filename tag for the corpus window ``[start, end)``; ``end=None`` = to the end."""
    if start < 0:
        raise ValueError(f"start must be >= 0, got {start}")
    if end is not None and end <= start:
        raise ValueError(f"end must be > start, got start={start} end={end}")
    return f"{start}_{'end' if end is None else end}"


def run_record_path(start: int, end: int | None) -> str:
    """results/run_record_<start>_<end>.json -- generation outcomes for one window."""
    return os.path.join(RESULTS_DIR, f"run_record_{window_tag(start, end)}.json")


def eval_headline_path(start: int, end: int | None) -> str:
    """results/eval_headline_<start>_<end>.json -- eval headline for one window."""
    return os.path.join(RESULTS_DIR, f"eval_headline_{window_tag(start, end)}.json")


def redos_report_path(start: int, end: int | None) -> str:
    """results/redos_<start>_<end>.json -- confirmed slow cases for one window."""
    return os.path.join(RESULTS_DIR, f"redos_{window_tag(start, end)}.json")


def redos_queue_path(start: int, end: int | None) -> str:
    """results/redos_queue_<start>_<end>.json -- DEFERRED, unconfirmed candidates.

    Written instead of a redos report under ``--redos-defer``. Deliberately a
    DIFFERENT filename from redos_<window>.json: a queue holds nominations measured
    under pool load, a report holds verdicts measured unloaded, and the whole point of
    the split is that those are not interchangeable. Sharing a name would let a
    consumer read nominations as findings.
    """
    return os.path.join(RESULTS_DIR, f"redos_queue_{window_tag(start, end)}.json")


def find_run_records() -> list[str]:
    """Every run_record_*.json present, sorted. Used to make a miss actionable."""
    import glob
    return sorted(glob.glob(os.path.join(RESULTS_DIR, "run_record_*.json")))


def ensure_regex_dir(rid: str) -> str:
    """Create results/<regex_id>/ and return it."""
    d = regex_dir(rid)
    os.makedirs(d, exist_ok=True)
    return d


def ensure_results_dirs() -> None:
    """Create the output directory tree if it does not exist yet."""
    for directory in (
        RESULTS_DIR,
        GENERATED_GRAMMARS_DIR,
        GENERATED_TEST_INPUTS_DIR,
        GENERATED_UNIT_TESTS_DIR,
        DIFF_TEST_RESULTS_DIR,
    ):
        os.makedirs(directory, exist_ok=True)
