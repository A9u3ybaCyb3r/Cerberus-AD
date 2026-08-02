"""Unit tests for cerberus-ad's ADSCAN_HOME state-directory isolation.

Regression coverage: upstream ADscan's get_adscan_home() hardcodes
~/.adscan (only overridable via the ADSCAN_HOME env var) with no awareness
of which console-script name invoked it. Without a fix, a separately
installed official `adscan` and this fork's `cerberus-ad` would read/write
the exact same host workspace directory -- the opposite of the "use both
without confusion" goal this fork exists for.
"""

import os
import sys

import pytest

from adscan_launcher.cli import _default_adscan_home_for_fork_entrypoint

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _restore_adscan_home_env():
    # The function under test mutates os.environ directly (not via
    # monkeypatch), so it isn't auto-reverted by monkeypatch's own teardown.
    # Snapshot/restore explicitly to keep tests isolated from each other.
    original = os.environ.get("ADSCAN_HOME")
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("ADSCAN_HOME", None)
        else:
            os.environ["ADSCAN_HOME"] = original


def test_sets_default_when_invoked_as_cerberus_ad(monkeypatch):
    monkeypatch.delenv("ADSCAN_HOME", raising=False)
    monkeypatch.setattr(sys, "argv", ["/home/user/.local/bin/cerberus-ad", "check"])
    _default_adscan_home_for_fork_entrypoint()
    assert os.environ.get("ADSCAN_HOME") == os.path.expanduser("~/.cerberus-ad")


def test_does_not_set_when_invoked_as_official_adscan(monkeypatch):
    monkeypatch.delenv("ADSCAN_HOME", raising=False)
    monkeypatch.setattr(sys, "argv", ["/home/user/.local/bin/adscan", "check"])
    _default_adscan_home_for_fork_entrypoint()
    assert os.environ.get("ADSCAN_HOME") is None


def test_explicit_adscan_home_always_wins(monkeypatch):
    monkeypatch.setenv("ADSCAN_HOME", "/custom/path")
    monkeypatch.setattr(sys, "argv", ["/home/user/.local/bin/cerberus-ad", "check"])
    _default_adscan_home_for_fork_entrypoint()
    assert os.environ.get("ADSCAN_HOME") == "/custom/path"
