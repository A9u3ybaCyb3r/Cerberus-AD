"""Integration-style tests for the attack-path cache's disk L2 layer and the
excluded_relations cache-key fix, exercised through the real
compute_display_paths_for_user entry point (not just the pure cache helpers).

Regression coverage:
- excluded_relations used to be silently absent from the cache key in all
  three scopes (user/domain/principals), so calling attack_paths again with
  a different --exclude-edges value in the same session could incorrectly
  return the previous, differently-filtered cached result.
- The disk cache lets a fresh process (a separate `cerberus-ad execute`
  invocation) reuse a previous computation instead of always recomputing.
"""

from collections import OrderedDict
from types import SimpleNamespace

import pytest

from adscan_internal.services import attack_graph_service as svc
from adscan_internal.services import attack_paths_core

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated_memory_cache(monkeypatch):
    # _ATTACK_PATHS_COMPUTE_CACHE is a module-level global shared across the
    # whole test process -- swap in a fresh dict per test so cache hits from
    # one test can't leak into another (monkeypatch reverts automatically).
    monkeypatch.setattr(svc, "_ATTACK_PATHS_COMPUTE_CACHE", OrderedDict())


@pytest.fixture
def patched_engine(monkeypatch):
    """Stub graph loading and the DFS engine so only cache behavior is under test."""
    calls: list = []

    def fake_load_attack_graph(shell, domain):
        return {"nodes": {}, "edges": [], "schema_version": "1.2"}

    def fake_compute(*args, **kwargs):
        calls.append(kwargs.get("excluded_relations"))
        return [
            {"nodes": ["a", "b"], "relations": ["GenericWrite"], "from_label": "a", "to_label": "b"}
        ]

    monkeypatch.setattr(svc, "load_attack_graph", fake_load_attack_graph)
    monkeypatch.setattr(
        attack_paths_core, "compute_display_paths_for_start_node", fake_compute
    )
    return calls


def _shell(tmp_path):
    return SimpleNamespace(current_workspace_dir=str(tmp_path), domains_dir="domains")


def test_identical_calls_hit_the_cache(tmp_path, patched_engine):
    shell = _shell(tmp_path)
    svc.compute_display_paths_for_user(
        shell, "test.local", username="bob", max_depth=6, max_paths=10
    )
    svc.compute_display_paths_for_user(
        shell, "test.local", username="bob", max_depth=6, max_paths=10
    )
    assert len(patched_engine) == 1  # second call was a cache hit


def test_different_excluded_relations_is_not_a_cache_hit(tmp_path, patched_engine):
    shell = _shell(tmp_path)
    svc.compute_display_paths_for_user(
        shell,
        "test.local",
        username="bob",
        max_depth=6,
        max_paths=10,
        excluded_relations=None,
    )
    svc.compute_display_paths_for_user(
        shell,
        "test.local",
        username="bob",
        max_depth=6,
        max_paths=10,
        excluded_relations=frozenset({"genericwrite"}),
    )
    # Before the fix, this second call would have incorrectly reused the
    # first call's cached (unfiltered) result instead of recomputing.
    assert len(patched_engine) == 2


def test_disk_cache_serves_a_fresh_process_with_empty_memory_cache(
    tmp_path, patched_engine
):
    shell = _shell(tmp_path)
    svc.compute_display_paths_for_user(
        shell, "test.local", username="bob", max_depth=6, max_paths=10
    )
    assert len(patched_engine) == 1

    # Simulate a brand-new process: clear the in-memory L1 cache, but the
    # disk L2 cache under tmp_path (the "workspace") still has the entry.
    svc._ATTACK_PATHS_COMPUTE_CACHE.clear()

    svc.compute_display_paths_for_user(
        shell, "test.local", username="bob", max_depth=6, max_paths=10
    )
    # Still 1: the disk cache served the second call without recomputing.
    assert len(patched_engine) == 1
