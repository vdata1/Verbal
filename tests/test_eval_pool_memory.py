"""Regression guard for the ``futs`` leak that OOM-killed the 15050-20035 window.

``run_eval`` submits every ``(regex, api)`` unit to a ThreadPoolExecutor at once and
maps each Future to its identity in a ``futs`` dict. The original loop read that mapping
with ``futs[fut]``, which never removed anything -- so every completed Future stayed in
the dict, and a Future holds its result for as long as it lives. Each result is one
unit's full ``per_case`` payload (~2.8 MB), so memory grew linearly with units completed:
11.7 GiB at 3,500 units, 80 GiB (the container cap) at 28,750, where the kernel killed
it 77% of the way through a 14-hour phase.

The fix is ``futs.pop(fut)``. This is invisible in the output -- the headline numbers are
identical either way -- so nothing else in the suite would catch a revert. Hence a test
that asserts the retention invariant directly.
"""

import gc
import os
import re
import weakref
from concurrent.futures import ThreadPoolExecutor, as_completed

_EVAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "eval", "run_eval.py")


class _Payload:
    """Stand-in for a unit's per_case result. A plain class so it can be weakref'd
    (``list``/``dict`` can be too, but a named type makes failures readable)."""
    __slots__ = ("data", "__weakref__")

    def __init__(self, n):
        self.data = [n] * 64


def _drain(pop: bool, n: int = 40):
    """Run n units through the pool exactly as run_eval does.

    Returns ``(refs, futs)`` -- the caller must hold onto ``futs``, because it is the
    retainer under test. Collecting liveness after it goes out of scope would show every
    payload freed regardless of the access pattern, and the leak test would pass
    vacuously (which is exactly what an earlier version of this file did).
    """
    refs = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(_Payload, i): ("regex_%d" % i, "exec") for i in range(n)}
        for fut in as_completed(futs):
            rid, api = futs.pop(fut) if pop else futs[fut]
            result = fut.result()
            refs.append(weakref.ref(result))
            assert rid.startswith("regex_") and api == "exec"
            del result, fut          # the loop's own locals are not the leak under test
    return refs, futs


def test_popping_releases_completed_payloads():
    """With ``pop``, a completed unit's payload is collectable immediately."""
    refs, futs = _drain(pop=True)
    gc.collect()
    assert len(futs) == 0, "futs should be empty once every future has been consumed"
    alive = [r for r in refs if r() is not None]
    assert not alive, f"{len(alive)}/{len(refs)} payloads still retained after the loop"
    assert futs is not None            # keep the retainer alive across the assertions


def test_indexing_retains_every_payload():
    """The original ``futs[fut]`` keeps all of them alive -- this is the leak.

    Asserted so the guard above cannot pass vacuously: if a future Python release made
    ``as_completed`` drop the caller's references too, both tests would go green and the
    real guard would be silently dead.
    """
    refs, futs = _drain(pop=False)
    gc.collect()
    assert len(futs) == 40, "futs still holds every future when indexed"
    alive = [r for r in refs if r() is not None]
    assert len(alive) == len(refs), (
        f"expected the indexing pattern to retain all {len(refs)} payloads, got "
        f"{len(alive)}; if this fails the leak mechanism has changed and the fix in "
        f"run_eval.py should be re-justified")


def test_run_eval_pops_in_the_as_completed_loop():
    """Source guard: the shipped loop must not go back to ``futs[fut]``.

    Behavioural tests cannot see this -- results are identical either way -- so pin the
    access pattern in the file itself.
    """
    src = open(_EVAL).read()
    loop = re.search(r"for fut in as_completed\(futs\):(.*?)\n    #", src, re.S)
    assert loop, "could not locate the as_completed loop in eval/run_eval.py"
    body = loop.group(1)
    assert "futs.pop(fut)" in body, "run_eval must pop completed futures (memory leak)"
    assert not re.search(r"futs\[fut\]", body), \
        "futs[fut] retains every completed Future -- use futs.pop(fut)"
