import asyncio
import copy

import httpx
import pytest

from loldraft.lcu import Credentials, LcuMonitor, discover, parse_lockfile, parse_session


def test_lockfile_credentials_are_redacted(tmp_path):
    (tmp_path / "lockfile").write_text("LeagueClient:123:5555:SYNTHETIC_TOKEN:https")
    creds = discover(str(tmp_path))
    assert creds.port == 5555
    assert "SYNTHETIC_TOKEN" not in repr(creds)
    with pytest.raises(ValueError):
        parse_lockfile("LeagueClient:1:80:token:http")


def test_hover_replacement_locking_and_unknowns(sessions):
    drafts = [parse_session(s) for s in sessions]
    assert all(p.champion_id == 0 for p in drafts[0].allies + drafts[0].enemies)
    assert drafts[1].allies[0].champion_id == 222
    assert drafts[1].allies[0].state == "hover"
    assert drafts[2].allies[0].champion_id == 51
    assert drafts[3].allies[0].champion_id == 222
    assert drafts[3].allies[0].state == "locked"
    assert drafts[4].allies[1].champion_id == 412
    assert drafts[5].enemies[0].champion_id == 119
    assert drafts[5].enemies[1].champion_id == 0
    assert all(p.state == "locked" for p in drafts[6].allies + drafts[6].enemies)


def test_hidden_enemy_intents_and_identifiers_never_exposed(sessions):
    raw = copy.deepcopy(sessions[5])
    raw["theirTeam"][1].update(championPickIntent=222, puuid="SYNTHETIC_HIDDEN_ID", summonerId=123)
    draft = parse_session(raw)
    assert draft.enemies[1].champion_id == 0
    assert "SYNTHETIC_HIDDEN_ID" not in draft.model_dump_json()


def test_side_is_unknown_unless_explicit(sessions):
    raw = copy.deepcopy(sessions[0])
    raw.pop("myTeamId", None)
    assert parse_session(raw).side == "unknown"
    raw["myTeamId"] = 200
    assert parse_session(raw).side == "red"


def test_policy_gate_prevents_any_client_request(config):
    updates = []
    def forbidden(**kwargs):
        pytest.fail("Disabled LCU must not make an HTTP request")
    monitor = LcuMonitor(config, lambda *a, **kw: updates.append(a),
                         discover_fn=lambda: Credentials(5555, "SYNTHETIC"), client_factory=forbidden)
    asyncio.run(monitor.once())
    assert monitor.status == "disabled"
    assert monitor.available


def test_client_disconnect_restart_and_reconnect(config, sessions):
    config.lcu_enabled = config.riot_live_approved = True
    available = [Credentials(5555, "SYNTHETIC"), None, Credentials(5556, "SYNTHETIC_NEW")]
    updates, requests = [], []
    def transport(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/lol-champ-select/v1/session"
        assert request.url.host == "127.0.0.1"
        return httpx.Response(200, json=sessions[3])
    monitor = LcuMonitor(config, lambda draft, **kw: updates.append((draft, kw)),
                         discover_fn=lambda: available.pop(0),
                         client_factory=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(transport), **kw))
    asyncio.run(monitor.once())
    assert monitor.status == "connected"
    asyncio.run(monitor.once())
    assert monitor.status == "disconnected" and updates[-1][0] is None
    asyncio.run(monitor.once())
    assert monitor.status == "connected"
    assert requests[-1].url.port == 5556


def test_waiting_for_select_clears_stale_draft(config):
    config.lcu_enabled = config.riot_live_approved = True
    updates = []
    monitor = LcuMonitor(config, lambda d, **kw: updates.append(d),
                         discover_fn=lambda: Credentials(5555, "SYNTHETIC"),
                         client_factory=lambda **kw: httpx.AsyncClient(
                             transport=httpx.MockTransport(lambda r: httpx.Response(404)), **kw))
    asyncio.run(monitor.once())
    assert monitor.status == "connected"
    assert updates == [None]
