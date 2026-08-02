"""Unit tests for the disk-backed L2 attack-path results cache.

Regression coverage for the "help avoid recomputation on large domains, and
across separate `cerberus-ad execute` invocations" improvement: each
`execute` call starts a fresh process with an empty in-memory cache, so it
previously got zero benefit from caching at all. This persists computed
results under the workspace, keyed by the same graph/snapshot-mtime-bound
key the in-memory cache already uses, so it invalidates identically.
"""

from types import SimpleNamespace

import pytest

from adscan_internal.services import attack_paths_materialized_cache as mc

pytestmark = pytest.mark.unit


def _shell(tmp_path):
    return SimpleNamespace(current_workspace_dir=str(tmp_path), domains_dir="domains")


def test_key_hash_stable_for_equal_keys():
    key_a = ("example.local", "user", 123.0, None, ("bob", 6, 10))
    key_b = ("example.local", "user", 123.0, None, ("bob", 6, 10))
    assert mc.attack_path_results_key_hash(key_a) == mc.attack_path_results_key_hash(
        key_b
    )


def test_key_hash_differs_for_different_keys():
    key_a = ("example.local", "user", 123.0, None, ("bob", 6, 10, ()))
    key_b = ("example.local", "user", 123.0, None, ("bob", 6, 10, ("genericwrite",)))
    assert mc.attack_path_results_key_hash(key_a) != mc.attack_path_results_key_hash(
        key_b
    )


def test_key_hash_normalizes_frozensets_order_independently():
    key_a = ("d", "s", 1.0, None, (frozenset({"a", "b"}),))
    key_b = ("d", "s", 1.0, None, (frozenset({"b", "a"}),))
    assert mc.attack_path_results_key_hash(key_a) == mc.attack_path_results_key_hash(
        key_b
    )


def test_load_returns_none_when_no_file_exists(tmp_path):
    shell = _shell(tmp_path)
    result = mc.load_disk_cached_attack_path_results(
        shell=shell, domain="example.local", cache_key=("example.local", "user")
    )
    assert result is None


def test_persist_then_load_round_trips(tmp_path):
    shell = _shell(tmp_path)
    key = ("example.local", "user", 1.0, None, ("bob", 6))
    records = [{"nodes": ["a", "b"], "relations": ["GenericWrite"]}]

    mc.persist_attack_path_results_to_disk(
        shell=shell, domain="example.local", cache_key=key, records=records
    )
    loaded = mc.load_disk_cached_attack_path_results(
        shell=shell, domain="example.local", cache_key=key
    )
    assert loaded == records


def test_load_returns_none_for_corrupt_file(tmp_path):
    shell = _shell(tmp_path)
    key = ("example.local", "user", 1.0, None, ("bob", 6))
    cache_dir = mc.attack_path_results_cache_dir(shell, "example.local")
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{mc.attack_path_results_key_hash(key)}.json"
    path.write_text("not valid json{{{", encoding="utf-8")

    loaded = mc.load_disk_cached_attack_path_results(
        shell=shell, domain="example.local", cache_key=key
    )
    assert loaded is None


def test_persist_prunes_oldest_files_beyond_max_files(tmp_path):
    shell = _shell(tmp_path)
    domain = "example.local"

    for i in range(5):
        key = (domain, "user", 1.0, None, (f"user{i}", 6))
        mc.persist_attack_path_results_to_disk(
            shell=shell,
            domain=domain,
            cache_key=key,
            records=[{"nodes": [f"n{i}"]}],
            max_files=3,
        )

    cache_dir = mc.attack_path_results_cache_dir(shell, domain)
    remaining = list(cache_dir.glob("*.json"))
    assert len(remaining) == 3

    # The oldest entries (user0, user1) should have been evicted first.
    first_key = (domain, "user", 1.0, None, ("user0", 6))
    assert (
        mc.load_disk_cached_attack_path_results(
            shell=shell, domain=domain, cache_key=first_key
        )
        is None
    )
    last_key = (domain, "user", 1.0, None, ("user4", 6))
    assert (
        mc.load_disk_cached_attack_path_results(
            shell=shell, domain=domain, cache_key=last_key
        )
        is not None
    )


def test_disk_cache_entry_becomes_unreachable_when_key_changes(tmp_path):
    """Simulates graph-mtime-based invalidation: the key includes the mtime
    token, so a "changed graph" is just a different key -- the old entry is
    silently orphaned rather than incorrectly served."""
    shell = _shell(tmp_path)
    domain = "example.local"
    stale_key = (domain, "user", 100.0, None, ("bob", 6))
    fresh_key = (domain, "user", 200.0, None, ("bob", 6))  # graph mtime changed

    mc.persist_attack_path_results_to_disk(
        shell=shell, domain=domain, cache_key=stale_key, records=[{"nodes": ["old"]}]
    )
    assert (
        mc.load_disk_cached_attack_path_results(
            shell=shell, domain=domain, cache_key=fresh_key
        )
        is None
    )
