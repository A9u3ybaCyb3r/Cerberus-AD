"""Unit tests for the deadline/--timeout partial-result behavior.

Regression coverage for the "owned mode should return something rather than
either completing cleanly or OOM-killing with nothing salvaged" goal --
verifies the deadline check actually engages and returns collected results
instead of running to completion, using a synthetic graph large enough that
an artificially tiny deadline reliably triggers the early-return path.
"""

import time

import pytest

from adscan_internal.services.attack_graph_core import (
    compute_maximal_attack_paths_from_start,
    compute_paths_to_target,
)

pytestmark = pytest.mark.unit


def _node(kind="User", label=None):
    return {"kind": kind, "label": label}


def _edge(from_id, to_id, relation="GenericWrite"):
    return {"from": from_id, "to": to_id, "relation": relation, "status": "discovered"}


def _fanout_chain_graph(width=8, chain_len=4):
    """A source fanning out to `width` hubs, each starting a `chain_len`-deep
    chain -- enough branching simple paths that an immediate (already-passed)
    deadline is guaranteed to cut off exploration before it completes."""
    nodes = {"source": _node(label="source")}
    edges = []
    for w in range(width):
        prev = "source"
        for d in range(chain_len):
            node_id = f"h{w}_{d}"
            nodes[node_id] = _node(label=node_id)
            edges.append(_edge(prev, node_id))
            prev = node_id
    nodes["target"] = _node(kind="Group", label="target")
    for w in range(width):
        edges.append(_edge(f"h{w}_{chain_len - 1}", "target"))
    return {"nodes": nodes, "edges": edges}


def test_deadline_none_runs_to_completion():
    graph = _fanout_chain_graph(width=3, chain_len=2)
    paths = compute_maximal_attack_paths_from_start(
        graph,
        start_node_id="source",
        max_depth=10,
        target="all",
        terminal_mode="domain",
        target_node_id="target",
        deadline=None,
    )
    assert len(paths) == 3  # one path per hub, no deadline to cut it short


def test_already_passed_deadline_returns_early_with_partial_results():
    graph = _fanout_chain_graph(width=8, chain_len=4)
    past_deadline = time.monotonic() - 1.0  # already expired
    paths = compute_maximal_attack_paths_from_start(
        graph,
        start_node_id="source",
        max_depth=10,
        target="all",
        terminal_mode="domain",
        target_node_id="target",
        deadline=past_deadline,
    )
    # An already-expired deadline must not silently behave like "no deadline"
    # -- it should cut off well short of the full width=8 path count.
    assert len(paths) < 8


def test_compute_paths_to_target_respects_expired_deadline():
    graph = _fanout_chain_graph(width=8, chain_len=4)
    past_deadline = time.monotonic() - 1.0
    paths = compute_paths_to_target(
        graph,
        start_node_ids=["source"],
        target_node_id="target",
        max_depth=10,
        max_paths=100,
        deadline=past_deadline,
    )
    assert paths == []  # deadline already gone before the first depth level runs


def test_future_deadline_does_not_truncate_a_fast_search():
    graph = _fanout_chain_graph(width=3, chain_len=2)
    generous_deadline = time.monotonic() + 30.0
    paths = compute_maximal_attack_paths_from_start(
        graph,
        start_node_id="source",
        max_depth=10,
        target="all",
        terminal_mode="domain",
        target_node_id="target",
        deadline=generous_deadline,
    )
    assert len(paths) == 3
