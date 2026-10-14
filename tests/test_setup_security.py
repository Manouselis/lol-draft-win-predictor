from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from loldraft.api import create_app
from loldraft.configuration import save_key, validate_key
from loldraft.desktop import child_command

TEST_KEY = "RG" + "API-" + str(UUID(int=1))  # Synthetic; never accepted by a real Riot API.


def test_setup_rejects_cross_site_and_missing_token_before_writing(config, monkeypatch):
    config.env_file = config.data_dir.parent / "private/.env"
    monkeypatch.setattr("loldraft.configuration.validate_key", lambda *_: None)
    with TestClient(create_app(config)) as client:
        token = client.get("/api/state").json()["configuration"]["setup_token"]
        assert client.post("/api/setup/key", json={"key": TEST_KEY}).status_code == 403
        assert client.post("/api/setup/key", json={"key": TEST_KEY}, headers={
            "X-League-Draft-Token": token, "Origin": "https://evil.example"}).status_code == 403
        assert client.post("/api/setup/key", content=TEST_KEY, headers={
            "X-League-Draft-Token": token, "Content-Type": "text/plain"}).status_code == 415
        assert not config.env_file.exists()


def test_saved_key_is_never_echoed_or_served_as_a_file(config, monkeypatch):
    config.env_file = config.data_dir.parent / "private/.env"
    monkeypatch.setattr("loldraft.configuration.validate_key", lambda *_: None)
    with TestClient(create_app(config)) as client:
        token = client.get("/api/state").json()["configuration"]["setup_token"]
        response = client.post("/api/setup/key", json={"key": TEST_KEY},
                               headers={"X-League-Draft-Token": token})
        assert response.status_code == 200
        assert TEST_KEY in config.env_file.read_text(encoding="utf-8")
        assert TEST_KEY not in response.text
        state = client.get("/api/state")
        assert state.json()["api_key_configured"] is True
        assert TEST_KEY not in state.text
        invalid = client.post("/api/setup/key", json={"key": {"secret": TEST_KEY}},
                              headers={"X-League-Draft-Token": token})
        assert invalid.status_code == 422
        assert TEST_KEY not in invalid.text
        assert client.get("/.env").status_code == 404
        assert client.get("/assets/../../.env").status_code == 404
        assert state.headers["X-Frame-Options"] == "DENY"


def test_validation_only_sends_key_to_riot_https_and_sanitizes_errors():
    seen = []
    def accepted(request):
        seen.append(request)
        return httpx.Response(200, json={})
    with httpx.Client(transport=httpx.MockTransport(accepted), follow_redirects=False) as client:
        validate_key(TEST_KEY, "EUW1", client=client)
    assert str(seen[0].url) == "https://euw1.api.riotgames.com/lol/status/v4/platform-data"
    assert seen[0].headers["X-Riot-Token"] == TEST_KEY
    for status in (302, 403, 500):
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
                status, headers={"Location": "https://evil.example"}, text=TEST_KEY)),
                follow_redirects=False) as client:
            with pytest.raises(ValueError) as raised:
                validate_key(TEST_KEY, "EUW1", client=client)
            assert TEST_KEY not in str(raised.value)


def test_key_replace_preserves_settings_and_failure_preserves_old_file(config, monkeypatch):
    config.env_file = config.data_dir.parent / "private/.env"
    config.env_file.parent.mkdir()
    config.env_file.write_text("RIOT_API_KEY=SYNTHETIC_OLD\nLOL_REGION=EUW1\n", encoding="utf-8")
    save_key(config, TEST_KEY)
    assert "LOL_REGION=EUW1" in config.env_file.read_text(encoding="utf-8")
    before = config.env_file.read_bytes()
    def fail_replace(*_):
        raise OSError("SYNTHETIC replacement failure")
    monkeypatch.setattr("loldraft.configuration.os.replace", fail_replace)
    with pytest.raises(OSError):
        save_key(config, "SYNTHETIC_SECOND")
    assert config.env_file.read_bytes() == before
    assert list(config.env_file.parent.iterdir()) == [config.env_file]


def test_production_testserver_host_and_malformed_origin_are_rejected(config):
    with TestClient(create_app(config), client=("127.0.0.1", 40000)) as client:
        assert client.get("/api/state").status_code == 403
        response = client.get("/api/state", headers={"Host": "127.0.0.1:8765", "Origin": "http://localhost:invalid"})
        assert response.status_code == 403


def test_background_child_arguments_never_contain_the_key(config):
    config.env_file = config.data_dir.parent / "private/.env"
    config.riot_key = TEST_KEY
    command = child_command(config, 8765)
    assert TEST_KEY not in " ".join(command)
    assert str(config.env_file) in command


def test_raw_upload_is_private_and_deleted_after_processing(config, monkeypatch):
    import threading
    private = config.data_dir.parent / "private-profile"
    monkeypatch.setattr("loldraft.api.private_state_dir", lambda: private)
    processed = threading.Event()
    seen = []
    def imported(path, *_args, **_kwargs):
        seen.append(path)
        assert path.parent == private / "imports"
        assert path.read_bytes() == b'{"SYNTHETIC_PRIVATE_FIELD":true}'
        processed.set()
        return {"accepted": 0}
    monkeypatch.setattr("loldraft.ingestion.import_file", imported)
    app = create_app(config)
    with TestClient(app) as client:
        response = client.post("/api/import", files={"file": ("test.json", b'{"SYNTHETIC_PRIVATE_FIELD":true}', "application/json")})
        assert response.status_code == 200
        assert processed.wait(2)
        import time
        for _ in range(20):
            if not seen[0].exists():
                break
            time.sleep(.01)
        assert not seen[0].exists()
        assert not (config.data_dir / "imports").exists()


def test_quit_requires_token_and_does_not_kill_training(config):
    from loldraft.locking import exclusive
    called = []
    app = create_app(config)
    app.state.shutdown_callback = lambda: called.append(True)
    with TestClient(app) as client:
        token = client.get("/api/state").json()["configuration"]["setup_token"]
        assert client.post("/api/quit", json={}).status_code == 403
        with exclusive(config.data_dir / "training.lock"):
            assert client.post("/api/quit", json={}, headers={"X-League-Draft-Token": token}).status_code == 409
            assert called == []
        response = client.post("/api/quit", json={}, headers={"X-League-Draft-Token": token})
        assert response.status_code == 200
        assert called == [True]
        assert app.state.runtime.shutting_down
        assert (config.data_dir / "collection.stop").exists()
