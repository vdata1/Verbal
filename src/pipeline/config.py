"""Resolved experiment configuration + provenance.

CLAUDE.md rules enforced here:
- Configuration over code: every experiment parameter is loaded from a versioned
  YAML file into a frozen dataclass. No tuned constant lives inline in the
  pipeline modules.
- Reproducibility: a single ``seed`` is threaded from config into both Python's
  ``random`` and Fandango's ``random_seed``. Every artifact records the four
  things a result must be traceable to: git commit, resolved-config hash, seed,
  and corpus (data) checksum -- see :func:`provenance`.
- Uniform treatment: the config carries only global knobs applied to every
  regex/API identically. There is no per-subject override mechanism, by design.

Fail loud: :func:`load_config` validates types and ranges and raises on anything
malformed rather than falling back to a default.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
from dataclasses import dataclass, asdict, fields

import yaml

from paths import PROJECT_ROOT

DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "default.yaml")


@dataclass(frozen=True)
class Config:
    """The fully-resolved, immutable experiment configuration.

    Field set is closed: an unknown key in the YAML is an error, not a silent
    ignore, so a typo in config can never quietly change (or fail to change) a run.
    """

    seed: int
    corpus: str                       # path relative to PROJECT_ROOT
    eval_slice: int                   # deterministic first-N corpus slice
    matchall_k: int                   # upper bound K for {2,K} matchAll rewrite
    pad_candidates: tuple[str, ...]   # ordered per-regex filler candidates
    flag_variants: tuple[str, ...]    # optional flag modifiers to test per harness
    chaos_n: int                      # boundary mutants per generated string (0 = off)
    chaos_ops: tuple[str, ...]        # enabled mutation ops (names in chaos.OPS)
    chaos_alphabet: tuple[str, ...]   # insert/substitute character pool
    fuzz_n: int                       # desired_solutions per .fan
    fuzz_max_generations: int
    fuzz_timeout_s: int
    neutral_count_timeout_s: int      # wall-clock budget for the py-re neutral oracle
    redos_slow_ms: int                # in-harness exec_ms above which a case is a ReDoS candidate
    redos_engine_ratio: float         # slowest/fastest engine factor that counts as engine-specific
    engines: tuple[str, ...]

    @property
    def corpus_path(self) -> str:
        """Absolute path to the corpus, resolved from PROJECT_ROOT."""
        return os.path.join(PROJECT_ROOT, self.corpus)


def load_config(path: str | None = None) -> Config:
    """Load and validate the resolved config from a YAML file.

    Raises on unknown keys, missing keys, or out-of-range values (fail loud).
    """
    path = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Config {path} must be a mapping, got {type(raw).__name__}")

    expected = {f.name for f in fields(Config)}
    unknown = set(raw) - expected
    if unknown:
        raise ValueError(f"Unknown config keys in {path}: {sorted(unknown)}")
    missing = expected - set(raw)
    if missing:
        raise ValueError(f"Missing config keys in {path}: {sorted(missing)}")

    cfg = Config(
        seed=int(raw["seed"]),
        corpus=str(raw["corpus"]),
        eval_slice=int(raw["eval_slice"]),
        matchall_k=int(raw["matchall_k"]),
        pad_candidates=tuple(str(p) for p in raw["pad_candidates"]),
        flag_variants=tuple(str(v) for v in raw["flag_variants"]),
        chaos_n=int(raw["chaos_n"]),
        chaos_ops=tuple(str(o) for o in raw["chaos_ops"]),
        chaos_alphabet=tuple(str(c) for c in raw["chaos_alphabet"]),
        fuzz_n=int(raw["fuzz_n"]),
        fuzz_max_generations=int(raw["fuzz_max_generations"]),
        fuzz_timeout_s=int(raw["fuzz_timeout_s"]),
        neutral_count_timeout_s=int(raw["neutral_count_timeout_s"]),
        redos_slow_ms=int(raw["redos_slow_ms"]),
        redos_engine_ratio=float(raw["redos_engine_ratio"]),
        engines=tuple(str(e) for e in raw["engines"]),
    )

    # --- Range / invariant checks (fail loud at the config boundary) ---------
    if cfg.eval_slice < 1:
        raise ValueError(f"eval_slice must be >= 1, got {cfg.eval_slice}")
    if cfg.matchall_k < 2:
        raise ValueError(f"matchall_k must be >= 2 (need >=2 matches), got {cfg.matchall_k}")
    if not cfg.pad_candidates:
        raise ValueError("pad_candidates must be non-empty")
    if any(len(p) != 1 for p in cfg.pad_candidates):
        raise ValueError("each pad candidate must be exactly one character")
    # The full JS flag alphabet: `d` (hasIndices) and `v` (unicodeSets) are both tested
    # variants now. A `v` variant does NOT need `u` stripped here -- regex_facts
    # ._canonical_flags resolves the u/v collision when it builds each harness's flag
    # string, so config only has to accept the letters.
    _VALID_FLAGS = set("dgimsuvy")
    for v in cfg.flag_variants:
        bad = set(v) - _VALID_FLAGS
        if bad:
            raise ValueError(f"flag_variants entry {v!r} has invalid flag(s) {sorted(bad)}; "
                             f"allowed: {sorted(_VALID_FLAGS)}")
        if len(set(v)) != len(v):
            raise ValueError(f"flag_variants entry {v!r} has a duplicated flag")
        if "u" in v and "v" in v:
            raise ValueError(f"flag_variants entry {v!r} requests both `u` and `v`, which "
                             "is a SyntaxError on every engine; use `v` alone (it subsumes `u`)")
    if cfg.chaos_n < 0:
        raise ValueError(f"chaos_n must be >= 0 (0 disables), got {cfg.chaos_n}")
    if cfg.chaos_n > 0:
        # Import here, not at module scope: pipeline.chaos is a leaf that imports
        # nothing from the pipeline, but config is imported by every stage, and a
        # top-level import would put chaos in every one of their import graphs.
        from pipeline.chaos import OPS as _CHAOS_OPS
        if not cfg.chaos_ops:
            raise ValueError("chaos_ops must be non-empty when chaos_n > 0")
        unknown_ops = [o for o in cfg.chaos_ops if o not in _CHAOS_OPS]
        if unknown_ops:
            raise ValueError(f"Unknown chaos_ops {unknown_ops}; "
                             f"known: {sorted(_CHAOS_OPS)}")
        if len(set(cfg.chaos_ops)) != len(cfg.chaos_ops):
            raise ValueError(f"chaos_ops has a duplicated op: {cfg.chaos_ops}")
        # insert/substitute draw from the alphabet; an empty pool would make them
        # silently inapplicable rather than loudly wrong.
        if not cfg.chaos_alphabet:
            raise ValueError("chaos_alphabet must be non-empty when chaos_n > 0")
        if any(len(c) != 1 for c in cfg.chaos_alphabet):
            raise ValueError("each chaos_alphabet entry must be exactly one character")
    if cfg.fuzz_n < 1:
        raise ValueError(f"fuzz_n must be >= 1, got {cfg.fuzz_n}")
    if cfg.fuzz_max_generations < 1:
        raise ValueError(f"fuzz_max_generations must be >= 1, got {cfg.fuzz_max_generations}")
    if cfg.fuzz_timeout_s < 1:
        raise ValueError(f"fuzz_timeout_s must be >= 1, got {cfg.fuzz_timeout_s}")
    if cfg.neutral_count_timeout_s < 1:
        raise ValueError(
            f"neutral_count_timeout_s must be >= 1, got {cfg.neutral_count_timeout_s}")
    if cfg.redos_slow_ms < 1:
        raise ValueError(f"redos_slow_ms must be >= 1, got {cfg.redos_slow_ms}")
    if cfg.redos_engine_ratio <= 1.0:
        # <=1 would flag every case: the slowest engine is always >= the fastest.
        raise ValueError(
            f"redos_engine_ratio must be > 1.0, got {cfg.redos_engine_ratio}")
    if not cfg.engines:
        raise ValueError("engines must be non-empty")
    return cfg


def seed_everything(config: Config) -> None:
    """Seed all process-level randomness from the single config seed.

    Fandango is seeded separately by passing ``random_seed=config.seed`` to
    ``fuzz(...)`` (see Stage 3); this covers any other ``random`` use.
    """
    random.seed(config.seed)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# Build-time commit snapshot, written by docker/build.sh into the image (the repo's
# .git is deliberately kept out of the image, so live `git` cannot run there). Read
# only as a FALLBACK when live git is unavailable -- see _git_commit.
_BAKED_COMMIT_FILE = os.path.join(PROJECT_ROOT, ".git-commit")


def _git_commit() -> str:
    """Current git commit hash, or 'unknown-<reason>' if unavailable.

    Resolution order:
      1. Live `git rev-parse HEAD` (+ `-dirty`) -- the true state of the running
         checkout; used for any bare-metal / in-repo run.
      2. The build-time baked value in ``.git-commit`` -- used inside the Docker
         image, where the repo's ``.git`` is intentionally excluded. This is a REAL
         hash captured from the host repo at image-build time (the exact code the
         image contains), not a fabricated one.
      3. ``unknown-<reason>`` -- neither available.

    Never silently fabricates a hash: a non-git/dirty state (live) or a missing bake
    is recorded verbatim so provenance never claims a clean commit it cannot prove.

    ``-c safe.directory=*`` is why step 1 works in a container. Bind-mounting the repo
    over ``/app`` (the normal way to run HEAD without a rebuild) makes git refuse with
    "detected dubious ownership" -- the tree is owned by the host uid, the container is
    root -- which exits non-zero and looks exactly like "not a git repo". That is how
    the 6000-10050 window came to record ``unknown-CalledProcessError`` for all 6.9M of
    its cases: the same bind mount ALSO shadowed the image's ``/app/.git-commit``, so
    both links of the chain broke at once.
    Reading the mounted tree is not merely a workaround, it is the only correct answer:
    when the repo is bind-mounted the code being executed IS the host tree, so falling
    back to the image's baked commit would confidently record a hash for code that is
    not running. The flag is per-invocation (no global git config is touched) and this
    call only ever reads a hash.
    """
    _GIT = ["git", "-c", "safe.directory=*"]
    try:
        commit = subprocess.run(
            _GIT + ["rev-parse", "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            _GIT + ["status", "--porcelain"],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        ).stdout.strip()
        return commit + ("-dirty" if dirty else "")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        baked = _read_baked_commit()
        return baked if baked else f"unknown-{type(e).__name__}"


def _read_baked_commit() -> str:
    """The build-time commit string from ``.git-commit``, or '' if absent/empty."""
    try:
        with open(_BAKED_COMMIT_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


def recorded_commit() -> str:
    """Exactly what :func:`provenance` will record for ``git_commit``.

    Public so a launcher can PREFLIGHT traceability instead of discovering after the
    fact that a whole window is untraceable. The 6000-10050 window recorded
    ``unknown-CalledProcessError`` for all 6.9M of its cases: the resolution chain
    below was correct, but the image had been built by plain ``docker compose build``
    (``GIT_COMMIT`` unset -> empty ``/app/.git-commit``), and nothing checked. A
    caller treats a value starting with ``unknown-`` as "do not spend a run on this".
    """
    return _git_commit()


# --- Chunk context (EXPERIMENT_GAPS G6, remaining item 2) --------------------
# The four provenance axes do not determine an artifact generated before `3ab1fc3`:
# generation depended on how many rows preceded a row IN ITS PROCESS, and chunk
# context was a hidden fifth input nothing recorded. HEAD is position-independent
# (each `_fuzz` forks a child and reseeds), so this is belt-and-braces rather than
# load-bearing -- but an artifact should still state how it was made instead of
# requiring a reader to know the driver's chunking defaults.
#
# Set ONCE per process by the entry point, alongside `seed_everything`. That is the
# correct scope, not a compromise: `overnight_run.py` is one fresh process per chunk,
# so a process-level value IS the chunk's identity. Unset stays unset -- the keys are
# emitted as null rather than omitted, so "nobody declared a chunk" is greppable and
# never mistaken for "generated as a whole window".
_CHUNK_CONTEXT: dict[str, int] | None = None


def set_chunk_context(start: int, count: int) -> None:
    """Declare the corpus chunk this process is generating, for provenance.

    ``start`` is the GLOBAL corpus index of the chunk's first row and ``count`` the
    number of rows the process was asked for -- together the exact ``--start`` /
    ``--count`` needed to regenerate this artifact.
    """
    global _CHUNK_CONTEXT
    if start < 0:
        raise ValueError(f"chunk start must be >= 0, got {start}")
    if count <= 0:
        raise ValueError(f"chunk count must be > 0, got {count}")
    _CHUNK_CONTEXT = {"chunk_start": start, "chunk_count": count}


def clear_chunk_context() -> None:
    """Forget any declared chunk context.

    Called by the eval before it computes its own provenance: chunk context is a
    GENERATION fact, and `--resume` compares provenance whole, so an eval that
    inherited a generation window's chunk would invalidate every cached diff.
    """
    global _CHUNK_CONTEXT
    _CHUNK_CONTEXT = None


def provenance(config: Config) -> dict:
    """The traceability facts every artifact must carry (CLAUDE.md).

    git_commit + config_sha + seed + corpus_sha pin a result to the code, parameters,
    randomness, and data that produced it; chunk_start/chunk_count pin the process
    slicing that a pre-`3ab1fc3` artifact also depended on (see the chunk-context
    block above). ``config_sha`` hashes the resolved config ONLY, so adding these
    keys leaves it unchanged and windows stay comparable across this commit.
    """
    resolved = asdict(config)
    config_sha = _sha256_text(json.dumps(resolved, sort_keys=True, ensure_ascii=True))
    chunk = _CHUNK_CONTEXT or {"chunk_start": None, "chunk_count": None}
    return {
        "git_commit": _git_commit(),
        "config_sha": config_sha,
        "seed": config.seed,
        "corpus": config.corpus,
        "corpus_sha": _sha256_file(config.corpus_path),
        **chunk,
        "resolved_config": resolved,
    }


def provenance_header_lines(config: Config, **extra: object) -> list[str]:
    """Provenance as `#`-comment lines to prepend to a `.fan`/`.js`/`.jsonl` artifact.

    Extra keyword args (e.g. api=..., regex_id=...) are appended verbatim so each
    artifact self-identifies. Comment lines are inert to Fandango and to JS.
    """
    prov = provenance(config)
    prov.pop("resolved_config")  # keep headers compact; full config lives in the run record
    prov.update(extra)
    lines = ["# provenance:"]
    for k, v in prov.items():
        lines.append(f"#   {k}: {v}")
    return lines
