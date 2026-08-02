"""CLI wrapper for `graph_stats` -- read-only attack-graph sizing, no LDAP calls.

Reads the same `attack_graph.json` `attack_paths` already reads (via
`load_attack_graph`), so it works against data collected by
`enum_domain_auth_phase1`/`start_auth` alike, and needs neither a live
connection nor attack-path discovery to have ever run.
"""

from __future__ import annotations

from typing import Any

from adscan_internal import print_info, print_warning
from adscan_internal.rich_output import mark_sensitive
from adscan_core.output._state import _get_console
from adscan_internal.services.attack_graph_service import (
    get_owned_domain_usernames_for_attack_paths,
    load_attack_graph,
)
from adscan_internal.services.attack_paths_core import _find_node_id_by_label
from adscan_internal.services.graph_stats_service import (
    DEFAULT_REACHABILITY_DEPTHS,
    DEFAULT_TOP_N,
    GraphStats,
    compute_graph_stats,
)


def run_graph_stats(
    shell: Any,
    target_domain: str,
    *,
    from_label: str | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> None:
    graph = load_attack_graph(shell, target_domain)
    nodes_map = graph.get("nodes") if isinstance(graph.get("nodes"), dict) else {}
    if not nodes_map:
        marked_domain = mark_sensitive(target_domain, "domain")
        print_warning(
            f"No attack graph data found for {marked_domain}. Run "
            "`enum_domain_auth_phase1 <domain>` (collection only, no attack-path "
            "discovery) or `start_auth <domain>` first."
        )
        return

    source_ids: set[str] = set()
    source_labels: list[str] = []
    if from_label:
        node_id = _find_node_id_by_label(graph, from_label)
        if not node_id:
            print_warning(f"No node found matching --from '{from_label}'.")
            return
        source_ids = {node_id}
        source_labels = [from_label]
    else:
        owned = get_owned_domain_usernames_for_attack_paths(shell, target_domain)
        for username in owned:
            node_id = _find_node_id_by_label(graph, username)
            if node_id:
                source_ids.add(node_id)
                source_labels.append(username)
        if not source_ids:
            print_warning(
                "No owned principals found for reachability estimates; pass "
                "--from <label> to pick an explicit source. Showing counts and "
                "top out-degree only."
            )

    stats = compute_graph_stats(
        graph,
        source_ids=source_ids,
        source_labels=source_labels,
        top_n=top_n,
    )
    _print_graph_stats(target_domain, stats)


def _print_graph_stats(domain: str, stats: GraphStats) -> None:
    from rich.table import Table

    marked_domain = mark_sensitive(domain, "domain")
    console = _get_console()

    print_info(
        f"Graph stats for {marked_domain}: {stats.node_count} nodes, "
        f"{stats.edge_count} edges."
    )

    if stats.top_out_degree:
        table = Table(title=f"Top {len(stats.top_out_degree)} by out-degree")
        table.add_column("Principal")
        table.add_column("Out-degree", justify="right")
        table.add_column("Top relation", justify="right")
        for entry in stats.top_out_degree:
            top_relation = max(entry.relations.items(), key=lambda kv: kv[1])
            table.add_row(
                mark_sensitive(entry.label, "user"),
                str(entry.out_degree),
                f"{top_relation[0]} x{top_relation[1]}",
            )
        console.print(table)

    if stats.source_labels:
        sources_display = ", ".join(
            mark_sensitive(label, "user") for label in stats.source_labels
        )
        print_info(f"Reachability estimate from: {sources_display}")
        for depth in DEFAULT_REACHABILITY_DEPTHS:
            count = stats.reachability_by_depth.get(depth, 0)
            print_info(f"  depth {depth}: ~{count} nodes reachable")

    print_info("Danger estimate:")
    for note in stats.danger_notes:
        print_warning(f"  {note}")
