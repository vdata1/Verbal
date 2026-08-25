"""Provenance completeness + the lastIndex preset battery's structural contract.

conftest.py puts ``src`` on the path. Pure/structural -- no Fandango, no engines.
The JS *behaviour* of the preset battery (search restoring lastIndex, match+g resetting
it, past-end producing null) needs real engines and is exercised by the differential
eval itself; what is pinned here is the shape, which is what silently regresses.
"""

import os

import pytest

from pipeline.config import (
    load_config, provenance, recorded_commit, set_chunk_context, clear_chunk_context,
)
from pipeline.api_descriptors import DESCRIPTORS, DESCRIPTORS_BY_API
from paths import PROJECT_ROOT

CONFIG = os.path.join(PROJECT_ROOT, "config", "smoke.yaml")


@pytest.fixture
def cfg():
    return load_config(CONFIG)


@pytest.fixture(autouse=True)
def _isolate_chunk_context():
    # Process-level state: never let one test's declaration leak into another's.
    clear_chunk_context()
    yield
    clear_chunk_context()


class TestRecordedCommit:
    """EXPERIMENT_GAPS G6: an untraceable window has to be re-run, so the launcher
    preflights this rather than discovering it in the headline afterwards."""

    def test_is_a_real_commit_in_this_checkout(self):
        # This repo has a .git, so resolution must reach step 1 and never fall through
        # to "unknown-". The 6000-10050 window recorded unknown-CalledProcessError
        # because a bind mount broke live git (dubious ownership) AND shadowed the
        # baked .git-commit at once; `-c safe.directory=*` is what fixes the first.
        rc = recorded_commit()
        assert rc, "empty commit string"
        assert not rc.startswith("unknown-"), rc
        head = rc[:-len("-dirty")] if rc.endswith("-dirty") else rc
        assert len(head) == 40 and all(c in "0123456789abcdef" for c in head), rc

    def test_matches_what_provenance_records(self, cfg):
        assert provenance(cfg)["git_commit"] == recorded_commit()


class TestChunkContext:
    """EXPERIMENT_GAPS G6 remaining item 2: chunk context was a hidden fifth input."""

    def test_absent_is_recorded_as_null_not_omitted(self, cfg):
        # Emitted-but-null, so "nobody declared a chunk" is greppable and can never be
        # confused with "generated as a whole window" or with an older artifact.
        p = provenance(cfg)
        assert p["chunk_start"] is None and p["chunk_count"] is None

    def test_declared_context_lands_in_provenance(self, cfg):
        set_chunk_context(5300, 100)
        p = provenance(cfg)
        assert (p["chunk_start"], p["chunk_count"]) == (5300, 100)

    def test_does_not_perturb_config_sha(self, cfg):
        # config_sha hashes the resolved config ONLY. If chunk context leaked into it,
        # every chunk would hash differently and windows would stop being comparable
        # across this commit -- including against the recorded 6000-10050 run.
        before = provenance(cfg)["config_sha"]
        set_chunk_context(6000, 100)
        assert provenance(cfg)["config_sha"] == before

    @pytest.mark.parametrize("start,count", [(-1, 100), (0, 0), (0, -5)])
    def test_rejects_impossible_context(self, start, count):
        # Fail loud: a bad declaration is a bug in the driver, not a value to record.
        with pytest.raises(ValueError):
            set_chunk_context(start, count)

    def test_clear_restores_undeclared_state(self, cfg):
        set_chunk_context(1, 2)
        clear_chunk_context()
        assert provenance(cfg)["chunk_start"] is None

    def test_cleared_provenance_matches_a_never_declared_one(self, cfg):
        """The `--resume` invariant, and the reason run_eval clears before stamping.

        `_load_valid_diff` compares provenance WHOLE. An in-process generate+eval run
        declares a chunk (generate_all does), so if the eval stamped that into each
        diff.json, the normal `--skip-generate --resume` path -- which declares no chunk
        -- would miss the cache on every unit and silently recompute the whole window.
        """
        fresh = provenance(cfg)
        set_chunk_context(6000, 250)
        clear_chunk_context()
        assert provenance(cfg) == fresh


class TestLastIndexPresetBattery:
    """The `d`/`y` flags activated the lastIndex *observation*; this activates the
    lastIndex *input*, which had never been varied from 0."""

    BATTERIED = ("exec", "test", "matchAll", "match", "search")
    # replace/replaceAll own a per-token lastIndex reset and their own token battery;
    # split owns a limit battery and never touches lastIndex at all (`Symbol.split`
    # works on an internal clone). Presets would cross-multiply those batteries for no
    # additional law, so all three stay out.
    NOT_BATTERIED = ("replace", "replaceAll", "split")
    RESET_PER_TOKEN = ("replace", "replaceAll")

    def test_helper_is_present_exactly_once_per_template(self):
        for d in DESCRIPTORS:
            assert d.template.count("function presetBattery(") == 1, d.api
            assert d.template.count("function lastIndexPresets(") == 1, d.api

    def test_presets_token_is_fully_substituted(self):
        # An unsubstituted token would be a JS syntax error on every engine, i.e. an
        # entire window of `ok: false` that looks like an engine result.
        for d in DESCRIPTORS:
            assert "__LASTINDEX_PRESETS__" not in d.template, d.api

    @pytest.mark.parametrize("api", BATTERIED)
    def test_read_only_apis_go_through_the_battery(self, api):
        assert "presetBattery(re, input," in DESCRIPTORS_BY_API[api].oracle

    @pytest.mark.parametrize("api", NOT_BATTERIED)
    def test_battery_apis_are_exactly_the_read_only_ones(self, api):
        assert "presetBattery" not in DESCRIPTORS_BY_API[api].oracle

    @pytest.mark.parametrize("api", RESET_PER_TOKEN)
    def test_token_batteries_keep_their_per_call_reset(self, api):
        # A sticky regex would otherwise carry lastIndex between tokens, making each
        # token's result depend on the previous one's match end.
        assert "re.lastIndex = 0" in DESCRIPTORS_BY_API[api].oracle

    def test_battery_records_the_left_behind_lastIndex(self):
        # Recording only the result would miss the whole point: save-and-restore
        # (search) and reset-to-0 (match+g) are laws about lastIndex AFTER the call.
        for d in DESCRIPTORS:
            assert "lastIndex: re.lastIndex" in d.template, d.api

    def test_preset_ladder_spans_start_middle_end_and_past_end(self):
        # Length-relative so one uniform rule means the same thing on a 5-char and a
        # 200-char string; past-the-end is the spec edge (no match + reset to 0).
        t = DESCRIPTORS_BY_API["exec"].template
        for expected in ("0, 1, Math.floor(s.length / 2), s.length, s.length + 1",):
            assert expected in t

    def test_non_stateful_value_bypasses_the_battery(self):
        # Without g/y, lastIndex is dead, so the value must pass straight through and
        # stay byte-identical to pre-preset artifacts. This axis is purely additive.
        t = DESCRIPTORS_BY_API["exec"].template
        assert "if (!re.global && !re.sticky) return call();" in t
