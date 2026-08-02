"""Unit tests for the parallel-principals shared-budget fix.

Regression coverage for a real bug: enabling ADSCAN_ATTACK_PATH_WORKERS for a
large `owned` run used to let every worker independently compute up to the
full max_paths per principal (principal_count x max_paths total, instead of
respecting the shared cap the sequential path already enforced) -- an OOM
vector that got worse the larger the domain and the more owned principals it
had, i.e. exactly the case parallel mode exists to help with.
"""

import pytest

from adscan_internal.services import attack_paths_core
from adscan_internal.services.attack_paths_core import (
    _next_remaining_budget,
    _principal_batches,
    _run_parallel_principals,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _next_remaining_budget
# ---------------------------------------------------------------------------


def test_next_remaining_budget_unlimited_when_max_paths_none():
    remaining, should_stop = _next_remaining_budget(None, produced_so_far=5)
    assert remaining is None
    assert should_stop is False


def test_next_remaining_budget_unlimited_when_max_paths_non_positive():
    remaining, should_stop = _next_remaining_budget(0, produced_so_far=5)
    assert remaining is None
    assert should_stop is False


def test_next_remaining_budget_capped_with_room():
    remaining, should_stop = _next_remaining_budget(10, produced_so_far=4)
    assert remaining == 6
    assert should_stop is False


def test_next_remaining_budget_exhausted_stops():
    remaining, should_stop = _next_remaining_budget(10, produced_so_far=10)
    assert remaining is None
    assert should_stop is True


def test_next_remaining_budget_already_over_stops():
    remaining, should_stop = _next_remaining_budget(10, produced_so_far=15)
    assert remaining is None
    assert should_stop is True


# ---------------------------------------------------------------------------
# _principal_batches
# ---------------------------------------------------------------------------


def test_principal_batches_exact_division():
    batches = _principal_batches(["a", "b", "c", "d"], 2)
    assert batches == [["a", "b"], ["c", "d"]]


def test_principal_batches_with_remainder():
    batches = _principal_batches(["a", "b", "c", "d", "e"], 2)
    assert batches == [["a", "b"], ["c", "d"], ["e"]]


def test_principal_batches_batch_size_larger_than_list():
    batches = _principal_batches(["a", "b"], 10)
    assert batches == [["a", "b"]]


def test_principal_batches_empty_list():
    assert _principal_batches([], 3) == []


def test_principal_batches_size_floored_at_one():
    batches = _principal_batches(["a", "b", "c"], 0)
    assert batches == [["a"], ["b"], ["c"]]


# ---------------------------------------------------------------------------
# _run_parallel_principals: shared-budget regression test
#
# A real ProcessPoolExecutor is overkill and flaky for a unit test, so a
# synchronous in-process fake pool stands in: submit() runs the target
# function immediately and wraps the result in a resolved Future, and the
# fake's initializer is invoked once on construction, mirroring how the real
# pool calls the initializer once per worker before any task runs.
# ---------------------------------------------------------------------------


class _ResolvedFuture:
    def __init__(self, result):
        self._result = result

    def result(self):
        return self._result


class _FakePool:
    def __init__(self, *, max_workers, mp_context, initializer, initargs):
        del max_workers, mp_context
        initializer(*initargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def submit(self, fn, *args):
        return _ResolvedFuture(fn(*args))


class _FakeAsCompleted:
    def __call__(self, futures):
        return iter(futures)


@pytest.fixture
def fake_pool(monkeypatch):
    import concurrent.futures

    monkeypatch.setattr(
        concurrent.futures, "ProcessPoolExecutor", _FakePool
    )
    monkeypatch.setattr(
        concurrent.futures, "as_completed", lambda futures: iter(futures)
    )


def test_parallel_principals_respects_shared_max_paths_budget(monkeypatch, fake_pool):
    per_principal_records = 5

    def fake_worker(username, max_paths_override):
        # Simulate a principal DFS that would produce `per_principal_records`
        # records if unbounded, but honors an explicit override when given
        # one -- exactly what compute_display_paths_for_user does.
        count = per_principal_records
        if isinstance(max_paths_override, int):
            count = min(count, max_paths_override)
        return [{"path": f"{username}-{i}"} for i in range(count)]

    monkeypatch.setattr(
        attack_paths_core, "_compute_paths_for_principal_worker", fake_worker
    )

    principals = [f"user{i}" for i in range(20)]
    records = _run_parallel_principals(
        principals,
        graph={},
        domain="example.local",
        snapshot=None,
        max_depth=6,
        max_paths=10,
        target="highvalue",
        target_mode="object",
        filter_shortest_paths=True,
        n_workers=2,
    )

    assert records is not None
    # Bounded to roughly n_workers x per-wave cap (2 workers x up to 10 each
    # in the worst single wave before the budget check catches up), NOT the
    # old unbounded 20 principals x 5 records/principal = 100.
    assert len(records) < 20
    assert len(records) <= 14
