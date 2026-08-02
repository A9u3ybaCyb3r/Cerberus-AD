"""Unit tests for build_easy_first_priority_key (the --easy-first sort mode).

Regression coverage for a real usability gap: the default canonical UX
ordering ranks target criticality far above path length/effort, so a long,
harder chain to a nominally more "important" target can outrank a one-hop
path (e.g. ADCS ESC1, which the shared effort catalog tags "high" effort even
though it's often the most practical real-world option) you can already
execute from a credential you hold. --easy-first exists to surface "what can
I actually go do right now" instead.
"""

import pytest

from adscan_internal.services.attack_step_support_registry import (
    build_easy_first_priority_key,
)

pytestmark = pytest.mark.unit


def _record(source, target, relations, length, **extra):
    return {
        "source": source,
        "target": target,
        "relations": relations,
        "length": length,
        **extra,
    }


def test_owned_start_sorts_before_unowned_start():
    owned_short_path = _record("alice", "dc01", ["ADCSESC1"], 1)
    unowned_short_path = _record("mallory", "dc02", ["ADCSESC1"], 1)
    owned = frozenset({"alice"})

    ordered = sorted(
        [unowned_short_path, owned_short_path],
        key=lambda r: build_easy_first_priority_key(r, owned_principals=owned),
    )
    assert ordered[0]["source"] == "alice"


def test_shorter_path_sorts_before_longer_path_for_same_ownership():
    short_path = _record("alice", "dc01", ["ADCSESC1"], 1)
    long_path = _record("alice", "dc02", ["GenericWrite", "GenericAll", "DCSync"], 3)
    owned = frozenset({"alice"})

    ordered = sorted(
        [long_path, short_path],
        key=lambda r: build_easy_first_priority_key(r, owned_principals=owned),
    )
    assert ordered[0]["target"] == "dc01"


def test_esc1_one_hop_beats_longer_chain_despite_high_effort_tag():
    """ADCSESC1 is tagged compromise_effort='high' in the shared catalog, but
    a 1-hop owned path should still outrank a 3-hop unowned/owned path,
    because length and ownership dominate the key -- this is the concrete
    scenario the feature was requested for."""
    esc1_path = _record("alice", "dc01", ["ADCSESC1"], 1, target_is_high_value=True)
    long_chain = _record(
        "alice",
        "dc02",
        ["GenericWrite", "GenericAll", "DCSync"],
        3,
        target_is_high_value=True,
    )
    owned = frozenset({"alice"})

    ordered = sorted(
        [long_chain, esc1_path],
        key=lambda r: build_easy_first_priority_key(r, owned_principals=owned),
    )
    assert ordered[0]["target"] == "dc01"


def test_no_owned_principals_given_falls_back_to_length_and_effort():
    short_path = _record("mallory", "dc01", ["ADCSESC1"], 1)
    long_path = _record("mallory", "dc02", ["GenericWrite", "GenericAll"], 2)

    ordered = sorted(
        [long_path, short_path],
        key=lambda r: build_easy_first_priority_key(r, owned_principals=None),
    )
    assert ordered[0]["target"] == "dc01"


def test_deterministic_tiebreak_on_source_and_target():
    a = _record("bob", "target-a", ["ADCSESC1"], 1)
    b = _record("bob", "target-b", ["ADCSESC1"], 1)

    ordered = sorted(
        [b, a], key=lambda r: build_easy_first_priority_key(r, owned_principals=None)
    )
    assert [r["target"] for r in ordered] == ["target-a", "target-b"]


def test_owned_principals_are_case_and_whitespace_normalized():
    record = _record("Alice.Wonderland", "dc01", ["ADCSESC1"], 1)
    owned = frozenset({" alice.wonderland "})

    key_owned = build_easy_first_priority_key(record, owned_principals=owned)
    key_unowned = build_easy_first_priority_key(record, owned_principals=frozenset())
    assert key_owned[0] == 0
    assert key_unowned[0] == 1
