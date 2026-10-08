def test_fault_presets(client):
    presets = client.get("/api/fault-presets").json()
    assert [p["name"] for p in presets] == [
        "stable",
        "flaky_stream",
        "slow_agent",
        "offline",
        "rate_limited",
        "server_error",
    ]
    assert presets[1]["rules"][0]["kind"] == "drop_stream" and presets[1]["description"]
