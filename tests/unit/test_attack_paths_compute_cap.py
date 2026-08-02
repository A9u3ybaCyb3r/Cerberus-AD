"""Unit tests for `_resolve_attack_paths_compute_cap`.

Regression coverage for the OOM root cause in `attack_paths <domain> owned`:
the compute-time path cap used to be unconditionally `None` (unbounded)
regardless of `--max`, because `_resolve_attack_paths_compute_cap` discarded
its `max_display` argument. See attack_graph_reports.py for the full story.
"""

import pytest

from adscan_internal.cli.attack_graph_reports import (
    ATTACK_PATHS_COMPUTE_DEFAULT_MAX,
    _ATTACK_PATHS_COMPUTE_FLOOR,
    _ATTACK_PATHS_COMPUTE_HEADROOM,
    _resolve_attack_paths_compute_cap,
)

pytestmark = pytest.mark.unit


def test_default_max_display_scales_with_headroom(monkeypatch):
    monkeypatch.delenv("ADSCAN_ATTACK_PATHS_COMPUTE_MAX", raising=False)
    assert _resolve_attack_paths_compute_cap(20) == 20 * _ATTACK_PATHS_COMPUTE_HEADROOM


def test_small_max_display_is_floored(monkeypatch):
    monkeypatch.delenv("ADSCAN_ATTACK_PATHS_COMPUTE_MAX", raising=False)
    assert _resolve_attack_paths_compute_cap(1) == _ATTACK_PATHS_COMPUTE_FLOOR


def test_large_max_display_scales_up(monkeypatch):
    monkeypatch.delenv("ADSCAN_ATTACK_PATHS_COMPUTE_MAX", raising=False)
    assert _resolve_attack_paths_compute_cap(500) == 500 * _ATTACK_PATHS_COMPUTE_HEADROOM


def test_non_positive_max_display_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("ADSCAN_ATTACK_PATHS_COMPUTE_MAX", raising=False)
    assert _resolve_attack_paths_compute_cap(0) == ATTACK_PATHS_COMPUTE_DEFAULT_MAX
    assert _resolve_attack_paths_compute_cap(-5) == ATTACK_PATHS_COMPUTE_DEFAULT_MAX


def test_compute_cap_is_never_unbounded_by_default(monkeypatch):
    """The specific regression this fix closes: no code path should return
    None (unbounded) for ordinary CLI usage anymore."""
    monkeypatch.delenv("ADSCAN_ATTACK_PATHS_COMPUTE_MAX", raising=False)
    assert _resolve_attack_paths_compute_cap(20) is not None
    assert ATTACK_PATHS_COMPUTE_DEFAULT_MAX is not None


def test_env_override_sets_hard_cap(monkeypatch):
    monkeypatch.setenv("ADSCAN_ATTACK_PATHS_COMPUTE_MAX", "42")
    assert _resolve_attack_paths_compute_cap(20) == 42
    # Env override wins even when max_display would otherwise dominate.
    assert _resolve_attack_paths_compute_cap(100000) == 42


def test_env_override_zero_or_negative_means_unlimited(monkeypatch):
    monkeypatch.setenv("ADSCAN_ATTACK_PATHS_COMPUTE_MAX", "0")
    assert _resolve_attack_paths_compute_cap(20) is None

    monkeypatch.setenv("ADSCAN_ATTACK_PATHS_COMPUTE_MAX", "-1")
    assert _resolve_attack_paths_compute_cap(20) is None


def test_env_override_invalid_value_falls_back_to_default_behavior(monkeypatch):
    monkeypatch.setenv("ADSCAN_ATTACK_PATHS_COMPUTE_MAX", "not-an-int")
    assert _resolve_attack_paths_compute_cap(20) == 20 * _ATTACK_PATHS_COMPUTE_HEADROOM
