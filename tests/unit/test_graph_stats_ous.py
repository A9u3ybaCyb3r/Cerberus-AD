"""Unit tests for graph_stats_service.list_organizational_units (--list-ous).

Regression coverage for a real usability gap: on an unfamiliar domain, the
OU tree is mostly noise -- BloodHound collects every LDAP container object
(including purely administrative/system ones) as kind="Container", and even
among true OUs, companies routinely keep old/decommissioned ones around
(process/political reasons) full of disabled accounts nobody deleted. Sorting
by raw object count would surface a legacy graveyard OU ahead of the one the
company actually operates out of -- sorting by *enabled* descendant count
fixes that.
"""

import pytest

from adscan_internal.services.graph_stats_service import list_organizational_units

pytestmark = pytest.mark.unit


def _ou(label, dn):
    return {"kind": "OU", "label": label, "properties": {"distinguishedname": dn}}


def _container(label, dn):
    return {"kind": "Container", "label": label, "properties": {"distinguishedname": dn}}


def _user(label, dn, *, enabled=True):
    return {
        "kind": "User",
        "label": label,
        "properties": {"distinguishedname": dn, "enabled": enabled},
    }


def _computer(label, dn, *, enabled=True):
    return {
        "kind": "Computer",
        "label": label,
        "properties": {"distinguishedname": dn, "enabled": enabled},
    }


def _group(label, dn):
    # Groups have no enabled/disabled concept.
    return {"kind": "Group", "label": label, "properties": {"distinguishedname": dn}}


def test_only_true_ou_kind_nodes_are_returned_not_containers():
    graph = {
        "nodes": {
            "ou1": _ou("Sales", "OU=Sales,DC=corp,DC=local"),
            "c1": _container("SOM", "CN=SOM,CN=WMIPolicy,CN=System,DC=corp,DC=local"),
        }
    }
    ous = list_organizational_units(graph)
    assert [ou.label for ou in ous] == ["Sales"]


def test_descendant_count_includes_nested_subtree():
    graph = {
        "nodes": {
            "ou1": _ou("Corp", "OU=Corp,DC=corp,DC=local"),
            "ou2": _ou("Sales", "OU=Sales,OU=Corp,DC=corp,DC=local"),
            "u1": _user("alice", "CN=alice,OU=Sales,OU=Corp,DC=corp,DC=local"),
            "u2": _user("bob", "CN=bob,OU=Corp,DC=corp,DC=local"),
        }
    }
    ous = {ou.label: ou for ou in list_organizational_units(graph)}
    # Corp's subtree includes everything under Sales too (transitively).
    assert ous["Corp"].descendant_object_count == 3  # Sales OU + alice + bob
    assert ous["Sales"].descendant_object_count == 1  # alice only


def test_does_not_count_itself_or_unrelated_ous():
    graph = {
        "nodes": {
            "ou1": _ou("Sales", "OU=Sales,DC=corp,DC=local"),
            "ou2": _ou("Marketing", "OU=Marketing,DC=corp,DC=local"),
            "u1": _user("alice", "CN=alice,OU=Marketing,DC=corp,DC=local"),
        }
    }
    ous = {ou.label: ou for ou in list_organizational_units(graph)}
    assert ous["Sales"].descendant_object_count == 0
    assert ous["Marketing"].descendant_object_count == 1


def test_sorted_by_enabled_count_not_raw_count():
    """The concrete scenario this feature was requested for: a legacy OU
    with many disabled leftover accounts should NOT outrank the OU the
    company is actually using, even though it has more total objects."""
    graph = {
        "nodes": {
            "ou_legacy": _ou("OldDept", "OU=OldDept,DC=corp,DC=local"),
            "ou_active": _ou("Corp", "OU=Corp,DC=corp,DC=local"),
        }
    }
    # 20 disabled stale accounts under the legacy OU.
    for i in range(20):
        graph["nodes"][f"stale{i}"] = _user(
            f"stale{i}", f"CN=stale{i},OU=OldDept,DC=corp,DC=local", enabled=False
        )
    # Only 5 accounts under the active OU, but all enabled.
    for i in range(5):
        graph["nodes"][f"active{i}"] = _user(
            f"active{i}", f"CN=active{i},OU=Corp,DC=corp,DC=local", enabled=True
        )

    ous = list_organizational_units(graph)
    assert [ou.label for ou in ous] == ["Corp", "OldDept"]
    corp = ous[0]
    old = ous[1]
    assert corp.descendant_enabled_object_count == 5
    assert corp.descendant_object_count == 5
    assert old.descendant_enabled_object_count == 0
    assert old.descendant_object_count == 20


def test_groups_and_gpos_count_toward_total_but_not_enabled():
    graph = {
        "nodes": {
            "ou1": _ou("Sales", "OU=Sales,DC=corp,DC=local"),
            "g1": _group("Sales Team", "CN=Sales Team,OU=Sales,DC=corp,DC=local"),
        }
    }
    ous = list_organizational_units(graph)
    assert ous[0].descendant_object_count == 1
    assert ous[0].descendant_enabled_object_count == 0


def test_depth_reflects_ou_nesting():
    graph = {
        "nodes": {
            "ou1": _ou("Corp", "OU=Corp,DC=corp,DC=local"),
            "ou2": _ou("Sales", "OU=Sales,OU=Corp,DC=corp,DC=local"),
        }
    }
    ous = {ou.label: ou for ou in list_organizational_units(graph)}
    assert ous["Corp"].depth == 1
    assert ous["Sales"].depth == 2


def test_no_ous_returns_empty_list():
    graph = {
        "nodes": {
            "c1": _container("SOM", "CN=SOM,CN=System,DC=corp,DC=local"),
        }
    }
    assert list_organizational_units(graph) == []


def test_missing_nodes_key_returns_empty_list():
    assert list_organizational_units({}) == []


def test_computer_enabled_status_also_counted():
    graph = {
        "nodes": {
            "ou1": _ou("Servers", "OU=Servers,DC=corp,DC=local"),
            "c1": _computer(
                "WEB01", "CN=WEB01,OU=Servers,DC=corp,DC=local", enabled=True
            ),
            "c2": _computer(
                "OLDDC", "CN=OLDDC,OU=Servers,DC=corp,DC=local", enabled=False
            ),
        }
    }
    ous = list_organizational_units(graph)
    assert ous[0].descendant_object_count == 2
    assert ous[0].descendant_enabled_object_count == 1
