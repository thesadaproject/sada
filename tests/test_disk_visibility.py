"""The disk is whoever runs the server's concern: the operator when hosted, the mosque's administrators on their own
server. Decided on the server (the state is not even sent to the others), for the status and for the alert."""

from __future__ import annotations

import pytest
from conftest import PW, client
from test_diskwatch import Clock, Disk, watch  # noqa: F401

from sada import mode
from sada.backoffice import auth, live
from sada.config import Config

DISK = {"level": "critical", "free_gb": 1.2, "low_gb": 14.2, "critical_gb": 2.4}


@pytest.fixture
def status(monkeypatch):
    """The orchestrator's summary, with a disk state in it."""
    summary = {"ok": True, "state": "IDLE", "disk": dict(DISK), "commands": []}
    monkeypatch.setattr(live, "status_cached", lambda mosque, ttl=None, forcer=False: dict(summary))
    return summary


@pytest.fixture
def people(env):
    auth.create_user(env["conn"], env["mid"], "chef", PW, "admin", "Chef")  # a mosque administrator, not the operator
    auth.create_user(env["conn"], env["mid"], "resp", PW, "responsable", "Responsable")
    return env


def signed(env, username, hosted):
    c = client(env, username)
    if hosted:
        assert c.ecrire("/mosques/select", {"mosque_id": env["mid"]}).status_code == 200
    return c


def disk_of(c):
    d = c.get("/api/v1/live/regie").json()
    return d["live"].get("disk"), c.get("/api/v1/dashboard").json()["live"].get("disk")


def test_hosted_a_mosque_user_never_gets_the_disk(env, people, status, monkeypatch):
    monkeypatch.setenv("SADA_MODE", "hosted")
    for name in ("chef", "resp", "imam"):
        regie, dash = disk_of(signed(env, name, True))
        assert regie is None and dash is None, name  # not hidden by the front: not sent


def test_hosted_the_operator_gets_it(env, people, status, monkeypatch):
    monkeypatch.setenv("SADA_MODE", "hosted")
    regie, dash = disk_of(signed(env, "admin", True))  # `admin` is the platform administrator
    assert regie == DISK and dash == DISK


def test_self_hosted_the_mosque_administrator_gets_it_the_others_do_not(env, people, status, monkeypatch):
    monkeypatch.delenv("SADA_MODE", raising=False)
    assert disk_of(signed(env, "chef", False)) == (DISK, DISK)
    for name in ("resp", "imam"):
        assert disk_of(signed(env, name, False)) == (None, None), name


def test_a_status_without_disk_is_left_alone(env, people, monkeypatch):
    monkeypatch.setattr(live, "status_cached", lambda mosque, ttl=None, forcer=False: {"ok": True, "state": "IDLE"})
    assert client(env, "chef").get("/api/v1/live/regie").json()["live"].get("disk") is None


def test_the_command_answer_does_not_leak_it_either(env, people, status, monkeypatch):
    monkeypatch.setenv("SADA_MODE", "hosted")
    assert live.without_disk({"disk": DISK, "state": "X"}) == {"disk": None, "state": "X"}
    assert live.without_disk({"state": "X"}) == {"state": "X"}


# ------------------------------------------------------------------ the alert


def test_hosted_the_mosque_is_never_alerted(monkeypatch):
    from sada import diskwatch
    from sada import orchestrator as orch

    monkeypatch.setenv("SADA_MODE", "hosted")
    sent: list[str] = []
    notifier = type("N", (), {"send": staticmethod(sent.append)})()
    w = diskwatch.DiskWatch(
        Config(), orch.disk_alert_channel(notifier), log=lambda m: None, usage=Disk(1), clock=Clock()
    )
    assert w.poll(force=True) == diskwatch.CRITICAL
    assert sent == []  # the log (and the telemetry gauge) are the operator's channels


def test_self_hosted_the_mosque_is_alerted_as_before(monkeypatch):
    from sada import diskwatch
    from sada import orchestrator as orch

    monkeypatch.delenv("SADA_MODE", raising=False)
    sent: list[str] = []
    notifier = type("N", (), {"send": staticmethod(sent.append)})()
    w = diskwatch.DiskWatch(
        Config(), orch.disk_alert_channel(notifier), log=lambda m: None, usage=Disk(1), clock=Clock()
    )
    w.poll(force=True)
    assert len(sent) == 1 and "critical" in sent[0]


def test_the_constructor_wires_that_channel():
    import inspect

    from sada import orchestrator as orch

    assert "disk_alert_channel(self.notifier)" in inspect.getsource(orch.Orchestrator.__init__)


def test_the_mode_is_read_the_same_way_by_both_processes(monkeypatch):
    monkeypatch.setenv("SADA_MODE", "Hosted")
    assert mode.hosted() and auth.hosted()
    monkeypatch.setenv("SADA_MODE", "")
    assert not mode.hosted() and not auth.hosted()


def test_the_chart_and_the_preprod_give_the_orchestrators_the_mode():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "deploy"
    assert "SADA_MODE" in (root / "helm/sada/templates/orchestrators.yaml").read_text()
    compose = (root / "preprod/compose.yaml").read_text()
    assert compose.count("SADA_MODE: hosted") == 2  # the back office and the orchestrator
