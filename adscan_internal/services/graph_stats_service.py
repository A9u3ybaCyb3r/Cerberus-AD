"""Read-only statistics over an already-collected attack graph.

Lets an operator size up a domain's attack graph -- node/edge counts, which
principals control a disproportionate number of objects, how many nodes are
reachable at each hop depth -- *before* running `attack_paths`, instead of
discovering a fan-out problem via an OOM kill partway through a DFS.

Deliberately does no path enumeration anywhere in this module: out-degree is
a single O(E) pass and reachability is a level-by-level BFS where every node
is visited once total, so cost stays O(V+E) regardless of how deep the
requested depth buckets go. It never gets more expensive to run than the
graph itself is big, unlike attack_paths (whose cost is dominated by the
number of simple paths, which can be combinatorial in fan-out).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from adscan_internal.services import attack_graph_core

DEFAULT_TOP_N = 15
DEFAULT_REACHABILITY_DEPTHS: tuple[int, ...] = (1, 2, 3, 4)

# Thresholds behind the plain-language danger estimate. Deliberately
# conservative/approximate -- this is meant to flag "worth a second look
# before running attack_paths", not to precisely predict DFS cost.
_HIGH_FANOUT_OUT_DEGREE = 100
_HIGH_REACHABILITY_RATIO = 0.25


@dataclass
class OutDegreeEntry:
    node_id: str
    label: str
    out_degree: int
    relations: dict[str, int] = field(default_factory=dict)


@dataclass
class GraphStats:
    node_count: int
    edge_count: int
    top_out_degree: list[OutDegreeEntry]
    reachability_by_depth: dict[int, int]
    source_labels: list[str]
    danger_notes: list[str]


@dataclass
class OrganizationalUnit:
    node_id: str
    label: str
    distinguished_name: str
    depth: int
    descendant_object_count: int
    descendant_enabled_object_count: int


def _label(nodes_map: dict[str, Any], node_id: str) -> str:
    node = nodes_map.get(node_id)
    if isinstance(node, dict):
        return str(node.get("label") or node_id)
    return node_id


def build_forward_adjacency(
    nodes_map: dict[str, Any], edges: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Same filtered-edge semantics the real DFS engine uses (minus virtual
    LocalAdminPassReuse expansion, which is per-visit and would require doing
    the DFS itself to compute) so degree/reachability numbers reflect what
    attack_paths would actually be able to traverse.
    """
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if attack_graph_core._is_nontraversable_attack_edge(edge, nodes_map):
            continue
        from_id = str(edge.get("from") or "").strip()
        to_id = str(edge.get("to") or "").strip()
        relation = str(edge.get("relation") or "").strip()
        if not from_id or not to_id or not relation:
            continue
        adjacency.setdefault(from_id, []).append(edge)
    return adjacency


def compute_top_out_degree(
    nodes_map: dict[str, Any],
    adjacency: dict[str, list[dict[str, Any]]],
    *,
    top_n: int = DEFAULT_TOP_N,
) -> list[OutDegreeEntry]:
    """Single O(E) pass; no traversal."""
    entries: list[OutDegreeEntry] = []
    for node_id, out_edges in adjacency.items():
        relations: dict[str, int] = {}
        for edge in out_edges:
            rel = str(edge.get("relation") or "unknown")
            relations[rel] = relations.get(rel, 0) + 1
        entries.append(
            OutDegreeEntry(
                node_id=node_id,
                label=_label(nodes_map, node_id),
                out_degree=len(out_edges),
                relations=relations,
            )
        )
    entries.sort(key=lambda e: e.out_degree, reverse=True)
    return entries[:top_n]


def compute_reachability_by_depth(
    adjacency: dict[str, list[dict[str, Any]]],
    *,
    source_ids: set[str],
    depths: tuple[int, ...] = DEFAULT_REACHABILITY_DEPTHS,
) -> dict[int, int]:
    """Cumulative reachable-node count at each requested hop depth.

    Level-by-level BFS: every node enters `visited` at most once across the
    whole call, so total cost is O(V+E) regardless of how many depth levels
    are requested or how deep they go -- this does NOT compound the way DFS
    path enumeration does, where cost grows with the number of distinct
    simple paths rather than the number of distinct nodes.
    """
    if not source_ids or not depths:
        return {d: 0 for d in depths}

    max_depth = max(depths)
    visited: set[str] = set(source_ids)
    frontier: set[str] = set(source_ids)
    result: dict[int, int] = {}

    for depth in range(1, max_depth + 1):
        next_frontier: set[str] = set()
        for node_id in frontier:
            for edge in adjacency.get(node_id, []):
                to_id = str(edge.get("to") or "").strip()
                if to_id and to_id not in visited:
                    visited.add(to_id)
                    next_frontier.add(to_id)
        frontier = next_frontier
        if depth in depths:
            result[depth] = len(visited)
        if not frontier:
            break

    # Depths beyond the last non-empty frontier plateau at the final count.
    last_count = len(visited)
    for d in depths:
        result.setdefault(d, last_count)
    return result


def _build_danger_notes(
    *,
    node_count: int,
    top_out_degree: list[OutDegreeEntry],
    reachability_by_depth: dict[int, int],
) -> list[str]:
    notes: list[str] = []

    for entry in top_out_degree:
        if entry.out_degree < _HIGH_FANOUT_OUT_DEGREE:
            break  # sorted descending; nothing after this clears the bar either
        top_relation = max(entry.relations.items(), key=lambda kv: kv[1])
        notes.append(
            f"'{entry.label}' controls {entry.out_degree} objects "
            f"(mostly '{top_relation[0]}', {top_relation[1]}x) -- a full-depth "
            "attack_paths search through this principal may fan out "
            "combinatorially. Consider --exclude-edges or a lower --depth."
        )

    if node_count > 0:
        for depth in sorted(reachability_by_depth):
            count = reachability_by_depth[depth]
            ratio = count / node_count
            if ratio >= _HIGH_REACHABILITY_RATIO:
                notes.append(
                    f"depth {depth} reaches an estimated {count} of {node_count} "
                    f"nodes ({ratio:.0%} of the graph) -- this may be expensive "
                    "to fully enumerate with attack_paths at that depth."
                )
                break  # first depth that crosses the bar is the one that matters

    if not notes:
        notes.append(
            "No high-fan-out principals or large reachable sets detected from "
            "these sources -- attack_paths should be safe to run at the default depth."
        )
    return notes


def list_organizational_units(graph: dict[str, Any]) -> list[OrganizationalUnit]:
    """Return every true OU in the graph, with how many other objects fall
    under its subtree -- the practical "which OU actually matters" signal.

    BloodHound collects every LDAP container object (including purely
    administrative/system ones like ``CN=Operations,CN=DomainUpdates,...``)
    as ``kind: "Container"``; only ``kind: "OU"`` nodes are true LDAP
    organizationalUnit objects, so filtering on that distinguishes real org
    structure from collection noise.

    Raw descendant count alone can still mislead: real domains routinely
    keep old/abandoned OUs around (a former department, a decommissioned
    site) full of disabled or otherwise stale accounts nobody deletes for
    process/political reasons, which can outnumber the objects in the OU
    that's actually in active use. ``descendant_enabled_object_count`` (only
    users/computers with ``properties.enabled`` true) is the sort key
    instead -- it's the count of what's actually live right now, not what
    happens to still be sitting there. Both counts are returned so the gap
    between them (e.g. 500 total vs. 12 enabled) is itself a visible signal
    of "this OU is legacy cruft, not where the company actually is."

    O(V^2) worst case (each OU scanned against every DN) -- fine at graph
    scale (thousands of nodes, not millions) and still far cheaper than any
    path enumeration.
    """
    nodes_map = graph.get("nodes") if isinstance(graph.get("nodes"), dict) else {}
    if not isinstance(nodes_map, dict):
        return []

    ou_candidates: list[tuple[str, dict[str, Any], str]] = []
    all_dns: list[tuple[str, bool]] = []  # (dn, is_enabled_or_unknown_kind)
    for node_id, node in nodes_map.items():
        if not isinstance(node, dict):
            continue
        props = (
            node.get("properties") if isinstance(node.get("properties"), dict) else {}
        )
        dn = str(props.get("distinguishedname") or "").strip()
        if dn:
            kind = str(node.get("kind") or "").strip().lower()
            if kind in {"user", "computer"}:
                enabled = bool(props.get("enabled"))
            else:
                # Groups/GPOs/OUs/etc. have no enabled/disabled concept --
                # count them toward "descendant objects" but not toward the
                # enabled-only signal, which is specifically about stale
                # accounts.
                enabled = False
            all_dns.append((dn, enabled))
        if str(node.get("kind") or "").strip().lower() == "ou":
            ou_candidates.append((node_id, node, dn))

    results: list[OrganizationalUnit] = []
    for node_id, node, dn in ou_candidates:
        if not dn:
            continue
        dn_lower = dn.lower()
        descendant_count = 0
        descendant_enabled_count = 0
        for other_dn, enabled in all_dns:
            other_dn_lower = other_dn.lower()
            if other_dn_lower == dn_lower or not other_dn_lower.endswith(
                "," + dn_lower
            ):
                continue
            descendant_count += 1
            if enabled:
                descendant_enabled_count += 1
        depth = sum(1 for part in dn.split(",") if part.strip().upper().startswith("OU="))
        results.append(
            OrganizationalUnit(
                node_id=node_id,
                label=str(node.get("label") or node_id),
                distinguished_name=dn,
                depth=depth,
                descendant_object_count=descendant_count,
                descendant_enabled_object_count=descendant_enabled_count,
            )
        )

    results.sort(key=lambda ou: ou.descendant_enabled_object_count, reverse=True)
    return results


def compute_graph_stats(
    graph: dict[str, Any],
    *,
    source_ids: set[str],
    source_labels: list[str] | None = None,
    top_n: int = DEFAULT_TOP_N,
    depths: tuple[int, ...] = DEFAULT_REACHABILITY_DEPTHS,
) -> GraphStats:
    nodes_map = graph.get("nodes") if isinstance(graph.get("nodes"), dict) else {}
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []

    adjacency = build_forward_adjacency(nodes_map, edges)
    top_out_degree = compute_top_out_degree(nodes_map, adjacency, top_n=top_n)
    reachability_by_depth = compute_reachability_by_depth(
        adjacency, source_ids=source_ids, depths=depths
    )
    danger_notes = _build_danger_notes(
        node_count=len(nodes_map),
        top_out_degree=top_out_degree,
        reachability_by_depth=reachability_by_depth,
    )

    return GraphStats(
        node_count=len(nodes_map),
        edge_count=len(edges),
        top_out_degree=top_out_degree,
        reachability_by_depth=reachability_by_depth,
        source_labels=source_labels or [],
        danger_notes=danger_notes,
    )
