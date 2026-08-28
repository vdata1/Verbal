"""Filesystem layout.

Single source of truth for every input and output location. Paths resolve from
the project root (derived from this file's location), not the current working
directory, so the layout is the same wherever the pipeline is launched from.

    <root>/data      input corpora
    <root>/src       pipeline code
    <root>/results   generated outputs
"""

import os

# This file lives at <root>/src/paths.py.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(PROJECT_ROOT, "data")

SRC_DIR = os.path.join(PROJECT_ROOT, "src")
PIPELINE_DIR = os.path.join(SRC_DIR, "pipeline")
# Node script used as the reference JS-regex validity gate (see pipeline/js_regex.py).
JS_REGEX_PROBE = os.path.join(PIPELINE_DIR, "js_regex_probe.js")

RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")

CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")


# --- Per-regex artifact layout -----------------------------------------------
# Every artifact for a regex lives under results/<regex_id>/, so all stages are
# joinable by id:
#
#   results/<regex_id>/base.fan               Stage 1, mutation-free
#   results/<regex_id>/<api>.fan              Stage 2, specialized per API
#   results/<regex_id>/<api>.strings.jsonl    Stage 3, generated strings
#   results/<regex_id>/<api>__<n>__<flags>.js Stage 3, synthesized harness
#   results/<regex_id>/<api>.diff.json        cross-engine diff
#
# The id is `regex_<n>`, n being the 0-based position of the regex in the corpus.
# Positional rather than a content hash: the corpus is a fixed, ordered file
# consumed via a deterministic slice, so positions are stable and human-legible.


def regex_id(index: int) -> str:
    """Stable id for the regex at 0-based corpus position `index`."""
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
    # One harness per (string, flag set).
    return os.path.join(regex_dir(rid), f"{api}__{n}__{harness_flag_tag(flags)}.js")


def api_diff_path(rid: str, api: str) -> str:
    return os.path.join(regex_dir(rid), f"{api}.diff.json")


# --- Per-window run artifacts ------------------------------------------------
# A run record and a headline describe ONE corpus window [start, end), and are
# named for it rather than written to a fixed path. With a fixed name a second
# window silently overwrites the first one's record, losing the earlier window's
# outcomes and leaving a headline that describes less than the results directory
# it sits in.


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
    """results/redos_queue_<start>_<end>.json -- deferred, unconfirmed candidates.

    Written instead of a report under ``--redos-defer``. Deliberately a different
    filename: a queue holds nominations measured under pool load, a report holds
    verdicts measured unloaded, and those are not interchangeable.
    """
    return os.path.join(RESULTS_DIR, f"redos_queue_{window_tag(start, end)}.json")


def find_run_records() -> list[str]:
    """Every run_record_*.json present, sorted."""
    import glob
    return sorted(glob.glob(os.path.join(RESULTS_DIR, "run_record_*.json")))


def ensure_regex_dir(rid: str) -> str:
    """Create results/<regex_id>/ and return it."""
    d = regex_dir(rid)
    os.makedirs(d, exist_ok=True)
    return d


def ensure_results_dirs() -> None:
    """Create the output directory tree if it does not exist yet."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
