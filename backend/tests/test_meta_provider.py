from backend import meta_provider


def test_baseten_uses_separate_key_and_fixed_model(monkeypatch):
    monkeypatch.setenv("META_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "synthetic-baseten")
    monkeypatch.setenv("META_API_KEY", "synthetic-meta")
    monkeypatch.setenv("META_MODEL", "wrong-model")
    provider, key, model, endpoint = meta_provider.config()
    assert provider == "baseten" and key == "synthetic-baseten"
    assert model == "meta-models/muse-spark-open-1026"
    assert endpoint == "https://inference.baseten.co/v1/chat/completions"


def test_meta_remains_default(monkeypatch):
    monkeypatch.delenv("META_PROVIDER", raising=False)
    monkeypatch.setenv("META_API_KEY", "synthetic-meta")
    assert meta_provider.config()[0:2] == ("meta", "synthetic-meta")
