"""Unit tests for graph_stats_service -- small synthetic graphs, no live lab."""

import pytest

from adscan_internal.services.graph_stats_service import (
    build_forward_adjacency,
    compute_graph_stats,
    compute_reachability_by_depth,
    compute_top_out_degree,
)

pytestmark = pytest.mark.unit


def _node(kind="User", label=None):
    return {"kind": kind, "label": label}


def _edge(from_id, to_id, relation="GenericWrite"):
    return {"from": from_id, "to": to_id, "relation": relation, "status": "discovered"}


def _chain_graph():
    """source -> a -> b -> c -> d, a 4-hop chain."""
    nodes = {
        "source": _node(label="source"),
        "a": _node(label="a"),
        "b": _node(label="b"),
        "c": _node(label="c"),
        "d": _node(label="d"),
    }
    edges = [
        _edge("source", "a"),
        _edge("a", "b"),
        _edge("b", "c"),
        _edge("c", "d"),
    ]
    return {"nodes": nodes, "edges": edges}


def _fanout_graph(fanout=6):
    """source -> hub -> n0..n{fanout-1}, hub has high out-degree."""
    nodes = {"source": _node(label="source"), "hub": _node(label="hub")}
    edges = [_edge("source", "hub")]
    for i in range(fanout):
        node_id = f"n{i}"
        nodes[node_id] = _node(label=node_id)
        edges.append(_edge("hub", node_id, relation="GenericWrite"))
    return {"nodes": nodes, "edges": edges}


def test_build_forward_adjacency_counts_edges():
    graph = _chain_graph()
    adjacency = build_forward_adjacency(graph["nodes"], graph["edges"])
    assert len(adjacency["source"]) == 1
    assert len(adjacency["a"]) == 1
    assert "d" not in adjacency  # terminal node, no outgoing edges


def test_top_out_degree_ranks_hub_first():
    graph = _fanout_graph(fanout=6)
    adjacency = build_forward_adjacency(graph["nodes"], graph["edges"])
    top = compute_top_out_degree(graph["nodes"], adjacency, top_n=5)
    assert top[0].label == "hub"
    assert top[0].out_degree == 6
    assert top[0].relations == {"GenericWrite": 6}


def test_top_out_degree_respects_top_n():
    graph = _fanout_graph(fanout=6)
    adjacency = build_forward_adjacency(graph["nodes"], graph["edges"])
    top = compute_top_out_degree(graph["nodes"], adjacency, top_n=1)
    assert len(top) == 1


def test_reachability_by_depth_matches_chain_length():
    graph = _chain_graph()
    adjacency = build_forward_adjacency(graph["nodes"], graph["edges"])
    counts = compute_reachability_by_depth(
        adjacency, source_ids={"source"}, depths=(1, 2, 3, 4)
    )
    # depth 1: {a} => 1 new node reachable (cumulative count excludes source itself
    # from the "reachable via traversal" perspective, but visited includes source).
    assert counts[1] == 2  # source + a
    assert counts[2] == 3  # + b
    assert counts[3] == 4  # + c
    assert counts[4] == 5  # + d


def test_reachability_plateaus_past_graph_end():
    graph = _chain_graph()
    adjacency = build_forward_adjacency(graph["nodes"], graph["edges"])
    counts = compute_reachability_by_depth(
        adjacency, source_ids={"source"}, depths=(4, 5, 10)
    )
    assert counts[4] == counts[5] == counts[10] == 5


def test_reachability_no_sources_returns_zero():
    graph = _chain_graph()
    adjacency = build_forward_adjacency(graph["nodes"], graph["edges"])
    counts = compute_reachability_by_depth(adjacency, source_ids=set(), depths=(1, 2))
    assert counts == {1: 0, 2: 0}


def test_compute_graph_stats_end_to_end():
    graph = _fanout_graph(fanout=6)
    stats = compute_graph_stats(
        graph, source_ids={"source"}, source_labels=["source"], top_n=3
    )
    assert stats.node_count == len(graph["nodes"])
    assert stats.edge_count == len(graph["edges"])
    assert stats.top_out_degree[0].label == "hub"
    assert stats.reachability_by_depth[1] == 2  # source + hub
    assert stats.danger_notes  # always non-empty


def test_danger_note_flags_high_fanout_principal():
    graph = _fanout_graph(fanout=150)
    stats = compute_graph_stats(graph, source_ids={"source"}, top_n=5)
    assert any("hub" in note and "150" in note for note in stats.danger_notes)


def test_danger_note_is_reassuring_when_nothing_stands_out():
    graph = _chain_graph()
    # Pad with unreachable nodes so the chain's depth-4 reachability stays a
    # small fraction of the graph -- otherwise a 5-node graph legitimately
    # reaches 100% of itself and *should* get a reachability note.
    for i in range(50):
        graph["nodes"][f"isolated{i}"] = _node(label=f"isolated{i}")
    stats = compute_graph_stats(graph, source_ids={"source"}, top_n=5)
    assert any("safe to run" in note for note in stats.danger_notes)
