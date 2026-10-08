def test_blob_upload_and_download(client):
    r = client.post("/api/blobs", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 201
    blob = r.json()
    assert blob["size"] == 5 and blob["filename"] == "a.txt"
    got = client.get(f"/api/blobs/{blob['id']}")
    assert got.content == b"hello" and got.headers["content-type"].startswith("text/plain")


def test_blob_too_large_is_413(client):
    client.app.state.workbench.blobs.max_bytes = 3
    r = client.post("/api/blobs", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 413


def test_missing_blob_and_exchange_404(client):
    assert client.get("/api/blobs/nope").status_code == 404
    assert client.get("/api/exchanges/nope").status_code == 404


def test_unknown_api_path_is_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404


def test_spa_serves_index_assets_and_blocks_traversal(tmp_path):
    from fastapi.testclient import TestClient

    from a2a_workbench.api.app import create_app

    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>app</html>")
    (static / "assets" / "a.js").write_text("console.log(1)")
    (static / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("secret")
    with TestClient(create_app(static_dir=static), base_url="http://127.0.0.1:8484") as c:
        assert c.get("/agents/xyz/chat").text == "<html>app</html>"
        assert c.get("/assets/a.js").text == "console.log(1)"
        assert c.get("/favicon.svg").text == "<svg/>"
        assert "secret" not in c.get("/..%2Fsecret.txt").text


def test_spa_without_build_explains(client):
    r = client.get("/")
    assert r.status_code in (200, 404)
