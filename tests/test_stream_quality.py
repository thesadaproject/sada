"""Broadcast quality per mosque: 720p by default, 1080p opt-in, read by the engine and by Sada Studio."""

import pytest

pytest.importorskip("fastapi")

from conftest import client, one  # noqa: E402,F401  (conftest provides the path)
from test_studio_devices import dev, heartbeat, pair  # noqa: E402

from sada import encoder, stream_quality  # noqa: E402
from sada.backoffice import internal, models, orm  # noqa: E402
from sada.config import Config  # noqa: E402


@pytest.fixture(autouse=True)
def _token(monkeypatch, tmp_path):
    monkeypatch.setenv("SADA_INTERNAL_TOKEN_FILE", str(tmp_path / "internal.token"))


def save(c, **body):
    return c.ecrire("/settings/quality", body, methode="PUT")


def engine_view(env):
    c = client(env)
    r = c.get("/api/v1/internal/stream-quality", headers={internal.HEADER: internal.token()})
    assert r.status_code == 200, r.text
    return r.json()


# --- back office -----------------------------------------------------------------------------


def test_720p_by_default(env):
    c = client(env, "admin")
    q = c.get("/api/v1/settings").json()["quality"]
    assert (q["height"], q["fps"], q["video_kbps"], q["effective_kbps"]) == (720, 30, 0, 2500)
    assert q["heights"] == [720, 1080] and q["fps_choices"] == [30, 60]
    e = engine_view(env)
    assert (e["width"], e["height"], e["fps"], e["video_kbps"], e["uplink_kbps"]) == (1280, 720, 30, 2500, 4500)


@pytest.mark.parametrize("saved", [0, 25])
def test_a_rate_saved_below_the_floor_reads_as_30(env, saved):
    orm.upsert(
        env["conn"], models.StreamQuality, ("mosque_id",), mosque_id=env["mid"], height=720, video_kbps=0, fps=saved
    )
    assert engine_view(env)["fps"] == 30


def test_1080p_saved_and_read_by_the_engine(env):
    c = client(env, "admin")
    r = save(c, height=1080, fps=30, video_kbps="")
    assert r.status_code == 200, r.text
    assert r.json()["quality"]["effective_kbps"] == 4500  # default of the resolution
    e = engine_view(env)
    assert (e["width"], e["height"], e["fps"], e["video_kbps"]) == (1920, 1080, 30, 4500)
    assert e["uplink_kbps"] == 8100
    save(c, height=1080, fps=60, video_kbps=6000)
    assert engine_view(env)["video_kbps"] == 6000
    assert one(env["conn"], models.StreamQuality, mosque_id=env["mid"])["height"] == 1080


@pytest.mark.parametrize(
    "body",
    [
        {"height": 480},
        {"height": 1080, "fps": 25},
        {"height": 1080, "fps": 120},
        {"height": 720, "video_kbps": 100},
        {"height": 720, "video_kbps": 99999},
        {"height": "abc"},
    ],
)
def test_invalid_values_refused(env, body):
    c = client(env, "admin")
    assert save(c, **body).status_code == 422
    assert engine_view(env)["height"] == 720  # nothing saved


def test_only_an_admin_changes_it(env):
    assert save(client(env, "responsable"), height=1080).status_code in (401, 403)
    assert engine_view(env)["height"] == 720


def test_internal_endpoint_needs_the_token(env):
    assert client(env).get("/api/v1/internal/stream-quality").status_code == 403


# --- Sada Studio -----------------------------------------------------------------------------


def test_studio_heartbeat_carries_the_quality(env):
    bearer, _ = pair(env)
    cfg = heartbeat(dev(env, bearer)).json()["config"]
    assert cfg["stream"]["height"] == 720 and cfg["stream"]["uplink_kbps"] == 4500 and cfg["stream"]["fps"] == 30
    save(client(env, "admin"), height=1080, fps=30)
    cfg = heartbeat(dev(env, bearer)).json()["config"]
    assert cfg["stream"] == {"width": 1920, "height": 1080, "fps": 30, "video_kbps": 4500, "uplink_kbps": 8100}


# --- engine side -----------------------------------------------------------------------------


def test_engine_reads_the_quality():
    seen = {}

    def fetch(url, token):
        seen["url"] = url
        return {"width": 1920, "height": 1080, "fps": 30, "video_kbps": 4500}

    got = stream_quality.from_backoffice("http://bo:8090", 8088, fetch=fetch)
    assert got == {"width": 1920, "height": 1080, "fps": 30, "video_bitrate": "4500k"}
    assert "/api/v1/internal/stream-quality" in seen["url"] and "port=8088" in seen["url"]


def test_engine_keeps_its_setting_when_the_back_office_fails_or_lies():
    def boom(url, token):
        raise OSError("down")

    assert stream_quality.from_backoffice("http://bo:8090", 8088, fetch=boom) == {}
    assert stream_quality.from_backoffice("", 8088) == {}
    nonsense = {"width": 10, "height": 10, "fps": 25, "video_kbps": 2500}
    assert stream_quality.from_backoffice("http://bo:8090", 8088, fetch=lambda u, t: nonsense) == {}
    assert stream_quality.from_backoffice("http://bo:8090", 8088, fetch=lambda u, t: {}) == {}


def test_ffmpeg_command_at_1080p(tmp_path):
    cfg = Config(width=1920, height=1080, fps=30, video_bitrate="4500k", rtmp_urls=["rtmp://127.0.0.1/x"])
    enc = encoder.Encoder(cfg, tmp_path, log=lambda m: None)
    cmd = enc.ffmpeg_cmd(None, None)
    assert "scale=1920:1080:force_original_aspect_ratio=decrease" in " ".join(cmd)
    assert cmd[cmd.index("-b:v") + 1] == "4500k"
    assert cmd[cmd.index("-bufsize") + 1] == "9000k"
    assert cmd[cmd.index("-g") + 1] == "60"


def test_buffer_size_unchanged_at_720p():
    assert encoder.bufsize("2500k") == "5000k"
    assert encoder.bufsize("garbage") == "5000k"


def test_the_engine_never_goes_below_30():
    got = stream_quality.from_backoffice(
        "http://bo:8090", 8088, fetch=lambda u, t: {"width": 1280, "height": 720, "fps": 25, "video_kbps": 2500}
    )
    assert got["fps"] == 30


def test_automatic_frame_rate_leaves_the_engine_alone():
    got = stream_quality.from_backoffice(
        "http://bo:8090", 8088, fetch=lambda u, t: {"width": 1280, "height": 720, "fps": 0, "video_kbps": 2500}
    )
    assert got == {"width": 1280, "height": 720, "video_bitrate": "2500k"}  # no "fps": SADA_FPS stays
