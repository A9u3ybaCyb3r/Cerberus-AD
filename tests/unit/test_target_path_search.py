"""Unit tests for compute_paths_to_target -- small synthetic graphs, no live lab."""

import pytest

from adscan_internal.services.attack_graph_core import compute_paths_to_target


pytestmark = pytest.mark.unit


def _node(kind="User", label=None):
    return {"kind": kind, "label": label}


def _edge(from_id, to_id, relation="GenericWrite"):
    return {"from": from_id, "to": to_id, "relation": relation, "status": "discovered"}


def _graph_with_shortest_and_decoy_paths():
    """source --GW--> a --GW--> target   (2-hop, shortest)
    source --GW--> b --GW--> c --GW--> target   (3-hop decoy, longer)
    """
    nodes = {
        "source": _node(label="source"),
        "a": _node(label="a"),
        "b": _node(label="b"),
        "c": _node(label="c"),
        "target": _node(kind="Group", label="target"),
    }
    edges = [
        _edge("source", "a"),
        _edge("a", "target"),
        _edge("source", "b"),
        _edge("b", "c"),
        _edge("c", "target"),
    ]
    return {"nodes": nodes, "edges": edges}


def test_returns_shortest_path_first():
    graph = _graph_with_shortest_and_decoy_paths()
    paths = compute_paths_to_target(
        graph,
        start_node_ids=["source"],
        target_node_id="target",
        max_depth=5,
        max_paths=10,
    )
    assert paths, "expected at least one path to the target"
    assert len(paths[0].steps) == 2
    assert paths[0].steps[-1].to_id == "target"
    # The 2-hop path must appear before the 3-hop decoy.
    lengths = [len(p.steps) for p in paths]
    assert lengths.index(2) < lengths.index(3)


def test_finds_both_paths_when_max_allows():
    graph = _graph_with_shortest_and_decoy_paths()
    paths = compute_paths_to_target(
        graph,
        start_node_ids=["source"],
        target_node_id="target",
        max_depth=5,
        max_paths=10,
    )
    lengths = sorted(len(p.steps) for p in paths)
    assert lengths == [2, 3]


def test_max_paths_caps_total_results():
    graph = _graph_with_shortest_and_decoy_paths()
    paths = compute_paths_to_target(
        graph,
        start_node_ids=["source"],
        target_node_id="target",
        max_depth=5,
        max_paths=1,
    )
    assert len(paths) == 1
    assert len(paths[0].steps) == 2  # the cap keeps the shortest one


def test_no_path_returns_empty():
    graph = {
        "nodes": {"source": _node(label="source"), "isolated": _node(label="isolated")},
        "edges": [],
    }
    paths = compute_paths_to_target(
        graph, start_node_ids=["source"], target_node_id="isolated", max_depth=5
    )
    assert paths == []


def test_unreachable_target_returns_empty():
    graph = _graph_with_shortest_and_decoy_paths()
    paths = compute_paths_to_target(
        graph,
        start_node_ids=["source"],
        target_node_id="does-not-exist",
        max_depth=5,
    )
    assert paths == []


def test_depth_limit_excludes_longer_decoy():
    graph = _graph_with_shortest_and_decoy_paths()
    paths = compute_paths_to_target(
        graph,
        start_node_ids=["source"],
        target_node_id="target",
        max_depth=2,
        max_paths=10,
    )
    assert len(paths) == 1
    assert len(paths[0].steps) == 2


def test_multiple_sources_shortest_first_across_sources():
    """A second source with a 1-hop path must be found before the 2-hop one
    from the first source, since depth is iterated before sources."""
    graph = _graph_with_shortest_and_decoy_paths()
    graph["nodes"]["source2"] = _node(label="source2")
    graph["edges"].append(_edge("source2", "target"))

    paths = compute_paths_to_target(
        graph,
        start_node_ids=["source", "source2"],
        target_node_id="target",
        max_depth=5,
        max_paths=10,
    )
    assert len(paths[0].steps) == 1
    assert paths[0].steps[0].from_id == "source2"
