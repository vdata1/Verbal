"""Stage 3 -- string generation + harness synthesis.

For one ``<api>.fan``: fuzz matching strings with Fandango (seeded, timeout-bounded
exactly as ``fuzz_ebnf.py`` does), write them to ``<api>.strings.jsonl``, and
synthesize one ``<api>__<n>.js`` execution harness per string from the descriptor's
template. Every harness prints the single canonical JSON line the eval runner diffs.

Uniform: the same fuzz + synthesis path runs for every regex and every API. The
per-API difference is entirely in ``descriptor`` data (template/oracle/flags).

Match-count policy (settled): we record a NEUTRAL Python-``re`` match count per
string as a prioritization signal only. We do NOT hard-filter strings by any
engine's match count -- dropping "too few matches" strings would mask exactly the
match-count discrepancies the project hunts (node sees 2, bun sees 1). Weak
strings (0-1 matches) are kept; per-engine counts are recorded downstream.

Two populations, one ``n`` space: the fuzz strings, then their chaos mutants
(:mod:`pipeline.chaos`) -- boundary inputs that deliberately may fall outside the
regex's language (see ``analysis/EXPERIMENT_GAPS.md`` G7). They are tested
identically and every record carries ``origin`` to tell them apart, because
``py_re_matches == 0`` means "the transpiler mis-modeled the regex" for a fuzz
string and "the mutation worked" for a chaos one. Any consumer of that oracle MUST
filter on ``origin``.

``py_re_matches`` is also THREE-valued: ``null`` means the neutral oracle did not
finish within ``neutral_count_timeout_s`` (Python ``re`` backtracks catastrophically
on nested quantifiers), NOT that the count was zero. Consumers MUST treat ``null`` as
unknown -- reading it as 0 would invent a miscompilation out of a timeout.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import random
import re as _re
import tempfile

from fandango import Fandango
from regex_fandango_transpiler import normalize_js_regex

# Fandango logs a flood of "Could not generate a full population" WARNINGs and
# "Only found N perfect solutions" (expected when a grammar has few unique strings
# -- documented noise, not a failure; see the handoff). Quiet WARNING-level so
# pipeline output is readable; ERROR+ stays visible. What actually matters (how
# many strings each API got) is recorded in strings.jsonl regardless.
logging.getLogger("fandango").setLevel(logging.ERROR)

from pipeline import chaos
from pipeline.api_descriptors import ApiDescriptor
from pipeline.config import Config, provenance, provenance_header_lines
from pipeline.regex_facts import (
    RegexFacts, analyze as analyze_regex, effective_flags, variant_flag_sets,
)
import paths


# JS regex flags that have a Python ``re`` equivalent (for the neutral oracle). The
# rest (``g`` global -> findall is already global; ``y`` sticky, ``u`` unicode ->
# Python ``str`` regex is always unicode) have no per-compile ``re`` flag.
_JS_TO_RE_FLAG = {"i": _re.IGNORECASE, "m": _re.MULTILINE, "s": _re.DOTALL}


def _re_flags(js_flags: str) -> int:
    bits = 0
    for f in js_flags:
        bits |= _JS_TO_RE_FLAG.get(f, 0)
    return bits


# One-generation probe size for estimating a grammar's unique-string count. Not a
# tuned magic number -- just "sample generously in one cheap generation to decide
# whether at least fuzz_n distinct strings exist" (matches old fuzz_ebnf.py).
_UNIQUE_ESTIMATE_PROBE = 100


def _fuzz_worker(fan_content: str, seed: int, fuzz_n: int, max_generations: int,
                 out_path: str, err_path: str) -> None:
    """Child-process fuzz: run Fandango and STREAM each unique solution as a JSON line
    to ``out_path`` (flushed per line). Runs in a forked child so the parent can
    hard-``SIGKILL`` a native fandango hang -- a Python ``signal.alarm`` handler (the
    old mechanism) can never preempt a search spinning inside Fandango's native code,
    which let a single pathological grammar burn 100% CPU indefinitely. Streaming to
    disk means a killed child still leaves every solution it had already found.

    ``random`` is reseeded here so the child's output depends only on
    ``(fan_content, seed)``, never on RNG state inherited at fork -- deterministic and
    reproducible. On an unexpected exception the traceback is written to ``err_path``
    and the child exits nonzero, so the parent can tell a genuine crash (re-raise ->
    recorded as this regex's ``error`` outcome) from a timeout kill (partial results).
    """
    logging.getLogger("fandango").setLevel(logging.ERROR)
    random.seed(seed)
    try:
        seen: set[str] = set()
        with open(out_path, "w") as out:
            def _collect(tree, index):
                s = str(tree)
                if s not in seen:
                    seen.add(s)
                    out.write(json.dumps(s) + "\n")
                    out.flush()  # survive a SIGKILL: parent reads via the OS buffer

            fdo = Fandango(fan_content, lazy=False, use_cache=False)
            # Cheap unique-string estimate (one generation, generous probe), then cap
            # the target so we don't chase more uniques than the grammar admits.
            estimate = len(fdo.fuzz(desired_solutions=_UNIQUE_ESTIMATE_PROBE,
                                    max_generations=1))
            target = max(1, min(fuzz_n, estimate)) if estimate > 0 else fuzz_n
            fdo.fuzz(
                desired_solutions=target,
                max_generations=max_generations,
                random_seed=seed,
                solution_callback=_collect,
            )
    except BaseException:
        import traceback
        with open(err_path, "w") as ef:
            ef.write(traceback.format_exc())
        os._exit(1)  # nonzero, without running atexit/finalizers in the child


def _read_solutions(out_path: str) -> list[str]:
    """Unique solutions (first-seen order) from the child's streamed JSONL. A trailing
    partial line -- the child SIGKILLed mid-``write`` -- is skipped, not fatal."""
    collected: list[str] = []
    seen: set[str] = set()
    with open(out_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
            except json.JSONDecodeError:
                continue  # truncated final line from a mid-write kill
            if s not in seen:
                seen.add(s)
                collected.append(s)
    return collected


def _fuzz(fan_content: str, config: Config) -> list[str]:
    """Seeded, HARD-timeout-bounded fuzz. Returns unique strings in first-seen order.

    Fandango runs in a forked child (:func:`_fuzz_worker`) with a wall-clock budget
    (``config.fuzz_timeout_s``). On expiry the child is ``SIGKILL``ed -- unlike the
    old in-process ``signal.alarm`` handler, ``SIGKILL`` preempts even a search
    spinning in native code (the real hang: a pathological grammar burned 100% CPU
    for hours because the Python alarm handler was never scheduled). Solutions are
    streamed to a temp file as they're found, so a killed run still returns everything
    collected so far -- never a silent empty success.

    Two behaviours are preserved from the old path:

    1. ``desired_solutions`` is capped at a cheap estimate of the grammar's unique
       strings, so we don't thrash chasing more uniques than the grammar admits.
    2. Determinism: the returned strings come from the seeded ``fuzz(random_seed=...)``
       call, and the child reseeds ``random`` (see :func:`_fuzz_worker`).

    A timeout yields partial results (the hardened, killable path). A child that dies
    on its own with a nonzero exit is a genuine crash: re-raised (fail loud) so
    :func:`process_row_range` records it as this regex's ``error`` outcome, exactly as
    an in-process exception would have.
    """
    ctx = multiprocessing.get_context("fork")
    out_fd, out_path = tempfile.mkstemp(suffix=".fuzz.jsonl")
    err_fd, err_path = tempfile.mkstemp(suffix=".fuzz.err")
    os.close(out_fd)
    os.close(err_fd)
    try:
        proc = ctx.Process(target=_fuzz_worker, args=(
            fan_content, config.seed, config.fuzz_n,
            config.fuzz_max_generations, out_path, err_path))
        proc.start()
        proc.join(config.fuzz_timeout_s)
        if proc.is_alive():
            proc.kill()  # SIGKILL: preempts the native-code hang the alarm couldn't
            proc.join(5)
            print(f"fandango:WARNING: fuzz exceeded {config.fuzz_timeout_s}s -- "
                  f"killed; using partial results", flush=True)
        elif proc.exitcode != 0:
            # Died on its own, nonzero: a real crash, not our timeout kill. Surface the
            # child's traceback and fail loud (recorded as this regex's error outcome).
            with open(err_path) as ef:
                child_tb = ef.read().strip()
            raise RuntimeError(
                f"fandango fuzz child exited {proc.exitcode}:\n{child_tb}")
        return _read_solutions(out_path)
    finally:
        for p in (out_path, err_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def _compile_neutral(pattern: str, flags: str = "") -> "_re.Pattern[str]":
    """Compile the neutral (Python-``re``) oracle for `pattern` under JS `flags`.

    Normalize the pattern the SAME way the transpiler does before ``sre_parse``
    (``normalize_js_regex``: ``\\u{...}`` code points + ``\\A``/``\\Z``/``\\z`` identity
    escapes): the transpiler accepts JS escapes that raw Python ``re`` reads
    differently or rejects, so using the un-normalized pattern here would crash or
    disagree with the grammar. This keeps the oracle in lock-step with the grammar
    the string was generated from.

    `flags` are the effective JS harness flags; the m/s/i subset is mapped to the
    matching ``re`` flags so the oracle agrees with the engine (e.g. a ``requires-m``
    regex is counted WITH ``re.MULTILINE``, matching the harness's ``m``).

    Compiled in the PARENT, deliberately: normalization/compilation is where a
    pattern-level exception (e.g. an unsupported ``\\p{...}``) is raised, and
    :func:`pipeline.run.process_row_range` classifies those into their own outcomes.
    Raising them inside the counting child would flatten every one into a generic
    ``error``. Compiling never backtracks -- only MATCHING does -- so nothing
    pathological happens here.
    """
    return _re.compile(normalize_js_regex(pattern), _re_flags(flags))


def _neutral_count_worker(rx: "_re.Pattern[str]", strings: list[str],
                          out_path: str, err_path: str) -> None:
    """Child-process neutral oracle: STREAM ``{i, count}`` per string to ``out_path``
    (flushed per line), so a SIGKILLed child still leaves every count it finished.

    Mirrors :func:`_fuzz_worker`, and for the same reason: ``re.findall`` runs in a
    single native call, so a Python ``signal.alarm`` handler is never scheduled and
    cannot preempt it. Only ``SIGKILL`` from the parent can.
    """
    try:
        with open(out_path, "w") as out:
            for i, s in enumerate(strings):
                out.write(json.dumps({"i": i, "count": len(rx.findall(s))}) + "\n")
                out.flush()  # survive a SIGKILL: parent reads via the OS buffer
    except BaseException:
        import traceback
        with open(err_path, "w") as ef:
            ef.write(traceback.format_exc())
        os._exit(1)  # nonzero, without running atexit/finalizers in the child


def _read_counts(out_path: str, n: int) -> list[int | None]:
    """The child's streamed counts, indexed 0..n-1. Anything the child never got to
    (timeout kill) stays ``None`` = NOT MEASURED. A trailing partial line -- killed
    mid-``write`` -- is skipped, not fatal."""
    counts: list[int | None] = [None] * n
    with open(out_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # truncated final line from a mid-write kill
            if 0 <= rec["i"] < n:
                counts[rec["i"]] = rec["count"]
    return counts


def _neutral_match_counts(pattern: str, strings: list[str], flags: str,
                          rid: str, api: str, config: Config) -> list[int | None]:
    """Neutral-oracle match counts for `strings`, HARD-bounded by
    ``config.neutral_count_timeout_s``. ``None`` for any string not measured in time.

    Python's ``re`` has no timeout and backtracks catastrophically on a nested
    quantifier (the real hang: ``#define\\s+(\\S+)+\\s+(\\S+)`` at corpus row 6580
    spun a chunk at 100% CPU for hours). The old code called ``re.findall`` inline,
    OUTSIDE the fuzz child, so ``fuzz_timeout_s`` -- which only ever wrapped
    :func:`_fuzz` -- could not bound it and the whole driver wedged indefinitely.

    Chaos made this reachable in practice: a mutant is a boundary string built to
    FAIL to match, and a failing match is exactly what forces the full exponential
    search, so the same regex that generated fine before chaos now hangs.

    Uniform mechanism (no per-regex logic): every regex gets the same budget, and the
    whole (regex, api) batch shares ONE forked child -- counting is otherwise cheap,
    and a fork per string would cost more than the oracle is worth. Counts stream
    out, so a kill keeps everything already measured (in practice: the fuzz strings,
    which are computed first and match quickly) and only the unmeasured tail goes
    ``None``.
    """
    if not strings:
        return []
    rx = _compile_neutral(pattern, flags)  # parent: see _compile_neutral's docstring
    ctx = multiprocessing.get_context("fork")
    out_fd, out_path = tempfile.mkstemp(suffix=".ncount.jsonl")
    err_fd, err_path = tempfile.mkstemp(suffix=".ncount.err")
    os.close(out_fd)
    os.close(err_fd)
    try:
        proc = ctx.Process(target=_neutral_count_worker,
                           args=(rx, strings, out_path, err_path))
        proc.start()
        proc.join(config.neutral_count_timeout_s)
        if proc.is_alive():
            proc.kill()  # SIGKILL: preempts the native re backtracking
            proc.join(5)
        elif proc.exitcode != 0:
            # Died on its own, nonzero: a real crash, not our timeout kill. Fail loud,
            # exactly as the old in-process call would have.
            with open(err_path) as ef:
                child_tb = ef.read().strip()
            raise RuntimeError(
                f"neutral-count child exited {proc.exitcode}:\n{child_tb}")
        counts = _read_counts(out_path, len(strings))
        n_unmeasured = sum(1 for c in counts if c is None)
        if n_unmeasured:
            # Loud + specific: silence here would read as "oracle says nothing to see"
            # on exactly the regexes most likely to be interesting.
            print(f"[{rid}] WARNING: neutral oracle exceeded "
                  f"{config.neutral_count_timeout_s}s on {api} -- "
                  f"{n_unmeasured}/{len(strings)} strings unmeasured "
                  f"(py_re_matches=null); /{pattern}/", flush=True)
        return counts
    finally:
        for p in (out_path, err_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def _string_records(strings: list[str], rid: str, api: str, pattern: str,
                    flags: str, config: Config) -> list[dict]:
    """The ``strings.jsonl`` string records: the fuzz strings, then their chaos
    mutants, in one contiguous ``n`` space.

    Mutants are appended AFTER every fuzz string (never interleaved), so ``n`` is
    stable for the fuzz population no matter what chaos does -- turning chaos off
    leaves fuzz-string ids untouched, and a diff artifact's ``n`` still means the
    same string it always did.

    Every record carries ``origin``. This is load-bearing, not decoration: the
    ``py_re_matches == 0`` miscompilation oracle
    (``analysis/eval_help_scripts/scan_miscompilations.py``) reads a non-matching
    string as proof the transpiler mis-modeled the regex -- which is exactly what a
    successful chaos mutant looks like. Those scanners filter on ``origin``; the
    field is what keeps a deliberate boundary input from being reported as a
    generation bug. A chaos record also carries ``seed_n`` + ``mutation``, which
    together with the config seed make it reconstructible from its seed string.

    ``py_re_matches`` is attached LAST, for every record in one bounded batch (see
    :func:`_neutral_match_counts`). It is ``null`` for a string the oracle could not
    measure within the budget -- distinct from ``0``, which asserts "the regex really
    does not match this string". Consumers must not conflate them: ``0`` is the
    miscompilation signal, ``null`` is the absence of a reading.
    """
    records = [
        {"kind": "string", "n": n, "string": s, "origin": "fuzz"}
        for n, s in enumerate(strings)
    ]
    if config.chaos_n >= 1:
        seen = set(strings)
        for seed_n, s in enumerate(strings):
            rng = chaos.rng_for(config.seed, rid, api, seed_n)
            for mutant, label in chaos.mutants(s, config.chaos_n, rng, config.chaos_ops,
                                               config.chaos_alphabet, seen):
                seen.add(mutant)
                records.append({
                    "kind": "string", "n": len(records), "string": mutant,
                    "origin": "chaos", "seed_n": seed_n, "mutation": label,
                })

    # One bounded child for the whole (regex, api) batch. Fuzz strings come first, so
    # a timeout on a pathological chaos mutant still keeps every fuzz reading.
    counts = _neutral_match_counts(pattern, [r["string"] for r in records],
                                   flags, rid, api, config)
    for record, count in zip(records, counts):
        # Neutral prioritization signal on the base flags; null = not measured.
        record["py_re_matches"] = count
    return records


def synthesize_harness(
    descriptor: ApiDescriptor, pattern: str, flags: str, string: str, rid: str, config: Config
) -> str:
    """Fill the descriptor's JS template for one (regex, string) into a harness."""
    prov_lines = provenance_header_lines(
        config, stage="harness", api=descriptor.api, regex_id=rid,
        flags=flags or "(none)",
    )
    prov_js = "\n".join("//" + line[1:] for line in prov_lines) + "\n"

    js = descriptor.template
    js = js.replace("__PROVENANCE__", prov_js)
    js = js.replace("__PATTERN__", json.dumps(pattern))
    js = js.replace("__FLAGS__", json.dumps(flags))
    js = js.replace("__INPUT__", json.dumps(string))
    js = js.replace("__API__", json.dumps(descriptor.api))
    js = js.replace("__REGEX_ID__", json.dumps(rid))
    return js


def generate_for_api(rid: str, descriptor: ApiDescriptor, pattern: str, config: Config,
                     facts: RegexFacts | None = None) -> dict:
    """Fuzz ``<api>.fan``, write strings + harnesses. Returns a summary record.

    `facts` is the Stage-1 :class:`RegexFacts`; derived from `pattern` if omitted.
    The harness flags are the API's mechanical flags UNION the regex's required
    flags, so a ``requires-m``/``requires-u`` regex is exercised the way its grammar
    was generated -- not with the bare per-API flag."""
    if facts is None:
        facts = analyze_regex(pattern)
    api = descriptor.api
    flags = effective_flags(descriptor.required_flags, facts.requires_flags)
    # Flag-variation dimension: one harness per (string, flag set). `variants[0]` is
    # the required-only base `flags`; the rest add the configured optional toggles.
    variants = variant_flag_sets(descriptor.required_flags, facts.requires_flags,
                                 config.flag_variants)
    fan_path = paths.api_fan_path(rid, api)
    with open(fan_path, "r") as f:
        fan_content = f.read()

    strings = _fuzz(fan_content, config)
    records = _string_records(strings, rid, api, pattern, flags, config)
    num_chaos = len(records) - len(strings)

    # --- write strings.jsonl (line 0 = meta/provenance, then one record/string) ---
    strings_path = paths.api_strings_path(rid, api)
    with open(strings_path, "w") as f:
        meta = {
            "kind": "meta", "regex_id": rid, "api": api, "pattern": pattern,
            "flags": flags, "api_required_flags": descriptor.required_flags,
            "regex_requires_flags": "".join(sorted(facts.requires_flags)),
            "flag_variants": variants,
            # `count` stays the TOTAL: the eval enumerates `range(count)` to find
            # cases, so mutants are picked up with no eval-side change. The split
            # is recorded alongside it -- G2's lesson is that an aggregate which
            # cannot be decomposed is an aggregate that hides things.
            "count": len(records),
            "count_fuzz": len(strings), "count_chaos": num_chaos,
            "provenance": provenance(config),
        }
        f.write(json.dumps(meta) + "\n")
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    # --- synthesize one harness per (string, flag variant) -------------------
    harness_paths = []
    for rec in records:
        for v in variants:
            js = synthesize_harness(descriptor, pattern, v, rec["string"], rid, config)
            hpath = paths.api_harness_path(rid, api, rec["n"], v)
            with open(hpath, "w") as f:
                f.write(js)
            harness_paths.append(hpath)

    return {
        "regex_id": rid, "api": api, "num_strings": len(records),
        "num_fuzz_strings": len(strings), "num_chaos_strings": num_chaos,
        "flag_variants": variants, "num_harnesses": len(harness_paths),
        "strings_path": strings_path, "harness_paths": harness_paths,
    }
