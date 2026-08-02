"""Unit tests for the attack-path cache's total-record memory budget.

Regression coverage: the LRU cache used to bound entry count and per-entry
record count independently, but not their product. A large domain with many
distinct owned principals produces many distinct cache keys (one per
principals-tuple/depth/target/scope combination); with each entry sitting
near its own per-entry cap, total cache memory could grow well past what
entry-count alone would suggest -- a slow, silent leak specific to working a
large domain over a long session.
"""

from collections import OrderedDict

import pytest

from adscan_internal.services import attack_graph_service as svc

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _attack_paths_cache_should_evict (pure)
# ---------------------------------------------------------------------------


def test_should_evict_false_under_both_budgets():
    assert (
        svc._attack_paths_cache_should_evict(
            5, 100, max_entries=10, max_total_records=1000
        )
        is False
    )


def test_should_evict_true_over_entry_budget_only():
    assert (
        svc._attack_paths_cache_should_evict(
            11, 100, max_entries=10, max_total_records=1000
        )
        is True
    )


def test_should_evict_true_over_total_records_budget_with_few_entries():
    # Only 3 entries (well under a max_entries=64 budget) but their combined
    # record count blows past the total-records budget -- this is exactly
    # the large-domain-many-owned-principals scenario this fix targets.
    assert (
        svc._attack_paths_cache_should_evict(
            3, 1500, max_entries=64, max_total_records=1000
        )
        is True
    )


# ---------------------------------------------------------------------------
# _attack_paths_cache_put: total-records eviction against the real cache
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_cache(monkeypatch):
    """Swap in a fresh cache + generous-but-finite budgets, restored after."""
    fresh_cache: "OrderedDict" = OrderedDict()
    monkeypatch.setattr(svc, "_ATTACK_PATHS_COMPUTE_CACHE", fresh_cache)
    monkeypatch.setattr(svc, "_ATTACK_PATHS_CACHE_ENABLED", True)
    monkeypatch.setattr(svc, "_ATTACK_PATHS_CACHE_MAX_ENTRIES", 64)
    monkeypatch.setattr(svc, "_ATTACK_PATHS_CACHE_MAX_RECORDS", 2000)
    monkeypatch.setattr(svc, "_ATTACK_PATHS_CACHE_MAX_TOTAL_RECORDS", 250)
    return fresh_cache


def _records(n, tag):
    return [{"path": f"{tag}-{i}"} for i in range(n)]


def test_total_records_budget_evicts_even_when_entry_count_is_fine(isolated_cache):
    # Entry count (3) stays far under max_entries (64), so the old
    # entry-count-only logic would never evict here -- but 3 x 100 = 300
    # records exceeds the new 250 total-records budget.
    svc._attack_paths_cache_put(("a",), _records(100, "a"), domain="d", scope="owned")
    svc._attack_paths_cache_put(("b",), _records(100, "b"), domain="d", scope="owned")
    assert len(isolated_cache) == 2  # still under budget after 2 entries

    svc._attack_paths_cache_put(("c",), _records(100, "c"), domain="d", scope="owned")

    total_records = sum(len(v) for v in isolated_cache.values())
    assert total_records <= 250
    # Oldest entry ("a") should have been evicted to make room.
    assert ("a",) not in isolated_cache
    assert ("c",) in isolated_cache


def test_deepcopy_isolation_on_cache_get(isolated_cache):
    # Pins the load-bearing deepcopy: mutating a record returned by a cache
    # hit must not corrupt what a later cache hit returns.
    svc._attack_paths_cache_put(
        ("x",), [{"path": "x-0", "_exact_signature": None}], domain="d", scope="owned"
    )
    first = svc._attack_paths_cache_get(("x",), domain="d", scope="owned")
    first[0]["_exact_signature"] = "mutated-in-place"

    second = svc._attack_paths_cache_get(("x",), domain="d", scope="owned")
    assert second[0]["_exact_signature"] is None
