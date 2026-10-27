def test_repair_option_has_been_removed(client):
    assert client.post("/api/model-repairs").status_code in (404, 405)
    assert client.post(
        "/api/model-repairs/unused/approve", json={"confirmed": True}
    ).status_code in (404, 405)
