import httpx
import pytest
from fastapi.testclient import TestClient

from loldraft.api import create_app
from loldraft.riot import RiotClient, RiotError
from loldraft.schemas import Draft, Pick


def test_manual_api_updates_without_inventing_predictions(config):
    with TestClient(create_app(config)) as client:
        assert client.get("/api/health").status_code == 200
        initial = client.get("/api/state").json()
        assert initial["prediction"]["probability"] is None
        draft = Draft(allies=[Pick(champion_id=222, state="hover")] + [Pick() for _ in range(4)])
        response = client.post("/api/draft", json=draft.model_dump())
        assert response.status_code == 200
        state = response.json()
        assert state["draft"]["allies"][0]["state"] == "hover"
        assert state["confirmed"]["probability"] is None
        assert state["history"][-1]["known"] == 1
        assert client.post("/api/mode", json={"mode": "live"}).status_code == 409
        assert client.post("/api/replay/5").json()["draft"]["enemies"][1]["champion_id"] == 0


def test_host_origin_and_secret_protection(config):
    config.riot_key = "SYNTHETIC_SECRET"
    with TestClient(create_app(config)) as client:
        response = client.get("/api/state")
        assert "SYNTHETIC_SECRET" not in response.text
        assert response.json()["api_key_configured"] is True
        assert client.post("/api/draft", json=Draft().model_dump(), headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/state", headers={"Host": "evil.example"}).status_code == 403


def test_duplicate_lock_rejected_but_unknown_slots_preserved(config):
    draft = Draft().model_dump()
    draft["allies"][0] = {"champion_id": 222, "state": "locked", "role": ""}
    draft["enemies"][0] = draft["allies"][0]
    with TestClient(create_app(config)) as client:
        assert client.post("/api/draft", json=draft).status_code == 422
        assert client.get("/api/state").json()["draft"]["allies"][0]["champion_id"] == 0


def test_429_honors_retry_after_without_exposing_key():
    calls, waits = [], []
    def transport(request):
        calls.append(request)
        assert request.headers["X-Riot-Token"] == "SYNTHETIC_KEY"
        return httpx.Response(429, headers={"Retry-After": "3"}) if len(calls) == 1 else httpx.Response(200, json={"ok": True})
    api = RiotClient("SYNTHETIC_KEY", client=httpx.Client(transport=httpx.MockTransport(transport)), throttle=False)
    api.pause = waits.append
    assert api.request("europe", "/lol/match/v5/matches/EUW1_1") == {"ok": True}
    assert waits == [3.1]
    assert len(calls) == 2


@pytest.mark.parametrize("status", [401, 403])
def test_expired_keys_stop_with_sanitized_message(status):
    api = RiotClient("SYNTHETIC_KEY", client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(status, text="SYNTHETIC_PRIVATE_BODY"))), throttle=False)
    with pytest.raises(RiotError) as raised:
        api.request("europe", "/lol/match/v5/matches/EUW1_1")
    assert "SYNTHETIC" not in str(raised.value)
    assert "expired" in str(raised.value)


def test_transient_api_failures_retry_and_404_is_graceful():
    statuses = [503, 502, 200]
    api = RiotClient("SYNTHETIC", client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(statuses.pop(0), json={"ok": True}))), throttle=False)
    api.pause = lambda _: None
    assert api.request("europe", "/lol/match/v5/matches/EUW1_1") == {"ok": True}
    api = RiotClient("SYNTHETIC", client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(404))), throttle=False)
    assert api.request("europe", "/lol/match/v5/matches/EUW1_1") is None


def test_keys_cannot_be_sent_to_arbitrary_hosts():
    api = RiotClient("SYNTHETIC", throttle=False)
    with pytest.raises(RiotError, match="Unrecognized Riot host"):
        api.request("evil.example", "/lol/match/v5/matches/x")
