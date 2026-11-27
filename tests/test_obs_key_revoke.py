"""The OBS stream key can be revoked from Settings: the picture comes from the Sada Studio."""

from __future__ import annotations

from conftest import client

from sada.backoffice import internal, live_input, models, orm


def _slug(env):
    return live_input.slug(orm.first(env["conn"], models.Mosque, id=env["mid"]))


def test_revoking_the_key_stops_obs_at_once(env):
    c = client(env, "admin")
    key = c.ecrire("/settings/input/key", {}).json()["key"]
    assert internal.publish_allowed(env["conn"], _slug(env), key)
    assert c.get("/api/v1/settings").json()["input"]["has_key"] is True
    r = c.ecrire("/settings/input/key", {}, methode="DELETE")
    assert r.status_code == 200 and r.json() == {"ok": True, "revoked": True}
    assert not internal.publish_allowed(env["conn"], _slug(env), key)
    assert c.get("/api/v1/settings").json()["input"]["has_key"] is False
    # nothing left: idempotent, nothing journaled twice
    assert c.ecrire("/settings/input/key", {}, methode="DELETE").json()["revoked"] is False


def test_only_an_administrator_with_csrf(env):
    c = client(env, "admin")
    c.ecrire("/settings/input/key", {})
    assert c.delete("/api/v1/settings/input/key").status_code == 403  # no CSRF header
    assert client(env, "responsable").ecrire("/settings/input/key", {}, methode="DELETE").status_code == 403
    assert c.get("/api/v1/settings").json()["input"]["has_key"] is True
