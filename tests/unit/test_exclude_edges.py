"""Unit tests for excluded_relations edge-type filtering -- small synthetic graphs."""

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


def _two_paths_graph():
    """source --GenericWrite--> target   (excludable path)
    source --AdminTo--> target           (allowed path)
    """
    nodes = {
        "source": _node(label="source"),
        "target": _node(kind="Group", label="target"),
    }
    edges = [
        _edge("source", "target", relation="GenericWrite"),
        _edge("source", "target", relation="AdminTo"),
    ]
    return {"nodes": nodes, "edges": edges}


def test_excluded_relation_is_dropped_from_traversal():
    graph = _two_paths_graph()
    paths = compute_paths_to_target(
        graph,
        start_node_ids=["source"],
        target_node_id="target",
        max_depth=5,
        max_paths=10,
        excluded_relations=frozenset({"genericwrite"}),
    )
    relations_used = {p.steps[0].relation for p in paths}
    assert "GenericWrite" not in relations_used
    assert "AdminTo" in relations_used


def test_no_exclusion_finds_both_relations():
    graph = _two_paths_graph()
    paths = compute_paths_to_target(
        graph,
        start_node_ids=["source"],
        target_node_id="target",
        max_depth=5,
        max_paths=10,
    )
    relations_used = {p.steps[0].relation for p in paths}
    assert relations_used == {"GenericWrite", "AdminTo"}


def test_excluding_all_relations_between_source_and_target_yields_no_path():
    graph = _two_paths_graph()
    paths = compute_paths_to_target(
        graph,
        start_node_ids=["source"],
        target_node_id="target",
        max_depth=5,
        max_paths=10,
        excluded_relations=frozenset({"genericwrite", "adminto"}),
    )
    assert paths == []


def test_exclusion_is_case_insensitive_at_the_dfs_level():
    graph = _two_paths_graph()
    # excluded_relations is documented as lower-cased already by the CLI
    # layer; confirm the DFS itself lower-cases the edge relation to compare.
    paths = compute_maximal_attack_paths_from_start(
        graph,
        start_node_id="source",
        max_depth=5,
        target="all",
        terminal_mode="domain",
        target_node_id="target",
        excluded_relations=frozenset({"genericwrite"}),
    )
    relations_used = {p.steps[0].relation for p in paths}
    assert "GenericWrite" not in relations_used
    assert "AdminTo" in relations_used


def test_excluding_unrelated_relation_has_no_effect():
    graph = _two_paths_graph()
    paths = compute_paths_to_target(
        graph,
        start_node_ids=["source"],
        target_node_id="target",
        max_depth=5,
        max_paths=10,
        excluded_relations=frozenset({"dcsync"}),
    )
    relations_used = {p.steps[0].relation for p in paths}
    assert relations_used == {"GenericWrite", "AdminTo"}
