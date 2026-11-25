"""Review fixes of the control room (regie) and its setup/custom-scene plumbing."""

from __future__ import annotations

import asyncio

from test_regie_studio import dev, engine  # noqa: F401  (fixture)

from sada.backoffice.api import regie


def _spy_on_loop(monkeypatch):
    """Replaces `live_flat` by a probe noting whether it ran on the event loop's thread."""
    on_loop: list[bool] = []
    real = regie.live_flat

    def probe(*a, **kw):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return real(*a, **kw)

    monkeypatch.setattr(regie, "live_flat", probe)
    return on_loop


def test_studio_async_routes_read_the_engine_off_the_event_loop(env, engine, monkeypatch):  # noqa: F811
    on_loop = _spy_on_loop(monkeypatch)
    d = dev(env)
    assert d.post("/api/v1/studio/live/command", json={"command": "scene", "arg": "khutba"}).status_code == 200
    assert d.patch("/api/v1/studio/live/overlays/qr", json={"visible": True, "url": "https://sada.example/q"}).status_code == 200
    assert len(on_loop) >= 2 and not any(on_loop), on_loop
