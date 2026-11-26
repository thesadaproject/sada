from sada.encoder import x264_preset


def test_default_is_ultrafast(monkeypatch):
    monkeypatch.delenv("SADA_X264_PRESET", raising=False)
    assert x264_preset() == "ultrafast"


def test_env_override(monkeypatch):
    monkeypatch.setenv("SADA_X264_PRESET", "Veryfast")
    assert x264_preset() == "veryfast"


def test_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("SADA_X264_PRESET", "bogus; rm")
    assert x264_preset() == "ultrafast"
