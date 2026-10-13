import copy
import threading

import httpx
import pytest

import loldraft.riot as riot
from loldraft.locking import CancelSignal, exclusive, is_locked
from loldraft.schemas import Settings
from loldraft.storage import Store


def test_collection_real_schema_dedup_dates_and_resume(tmp_path, raw, monkeypatch):
    store = Store(tmp_path)
    old = copy.deepcopy(raw)
    old["metadata"]["matchId"] = "EUW1_1"
    old["info"]["gameStartTimestamp"] = 1
    old["info"]["gameCreation"] = 1
    good_id = raw["metadata"]["matchId"]
    original = riot.RiotClient
    monkeypatch.setattr(original, "seed_players", lambda *args: iter([("SYNTHETIC_PUUID", "SILVER")]))
    monkeypatch.setattr(riot, "RiotClient", lambda *args, **kwargs: original(*args, throttle=False, **kwargs))
    def transport(request):
        if request.url.path.endswith("/ids"):
            assert int(request.url.params["startTime"]) > 0
            return httpx.Response(200, json=[good_id, good_id, "EUW1_1"])
        return httpx.Response(200, json=old if request.url.path.endswith("/EUW1_1") else raw)
    kwargs = {"client": httpx.Client(transport=httpx.MockTransport(transport))}
    result = riot.collect(store, Settings(), "SYNTHETIC_KEY", **kwargs)
    assert result["imported"] == 1
    assert result["rejected"] == 1
    assert store.stats()["matches"] == 1
    assert not store.pending("EUW1")
    result = riot.collect(store, Settings(), "SYNTHETIC_KEY", client=httpx.Client(transport=httpx.MockTransport(transport)))
    assert result["imported"] == 0
    assert store.stats()["matches"] == 1


def test_expired_key_keeps_pending_ids(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.enqueue(["EUW1_42"])
    original = riot.RiotClient
    monkeypatch.setattr(riot, "RiotClient", lambda *args, **kwargs: original(*args, throttle=False, **kwargs))
    with pytest.raises(riot.RiotError):
        riot.collect(store, Settings(), "SYNTHETIC_KEY", client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(403))))
    assert store.pending("EUW1") == ["EUW1_42"]


def test_collector_os_lock_and_cross_process_stop_marker(tmp_path):
    path = tmp_path / "job.lock"
    with exclusive(path):
        assert is_locked(path)
    assert not is_locked(path)
    marker = tmp_path / "job.stop"
    signal = CancelSignal(threading.Event(), marker)
    assert not signal.is_set()
    marker.write_text("stop")
    assert signal.is_set()
    assert signal.wait(120)
