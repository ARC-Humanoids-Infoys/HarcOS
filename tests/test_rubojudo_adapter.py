from robots.rubojudo_adapter import RubojudoAdapter


def test_adapter_falls_back_when_disabled():
    adapter = RubojudoAdapter(enabled=False)
    result = adapter.execute("stand_up")
    assert result["status"] == "skipped"
    assert result["action"] == "stand_up"


def test_adapter_falls_back_when_backend_missing():
    adapter = RubojudoAdapter(backend=None, enabled=False)
    result = adapter.execute("move", vx=0.1)
    assert result["status"] == "skipped"
