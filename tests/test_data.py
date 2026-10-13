import copy
import json

import pytest

from loldraft.champions import parse_catalog
from loldraft.ingestion import InvalidMatch, import_file, normalize
from loldraft.storage import Store


def test_normalization_discards_all_player_identifiers(raw):
    match = normalize(raw)
    assert match["region"] == "EUW1"
    assert match["patch"] == "16.20"
    assert len(match["blue"]) == len(match["red"]) == 5
    assert match["blue_win"] is True
    assert "SYNTHETIC_PRIVATE_FIELD" not in json.dumps(match)
    assert "puuid" not in json.dumps(match)


@pytest.mark.parametrize("change", [
    {"gameDuration": 300}, {"queueId": 450}, {"mapId": 12}, {"gameMode": "ARAM"},
    {"gameStartTimestamp": 1, "gameCreation": 1}, {"gameVersion": "unknown"},
])
def test_invalid_and_older_than_month_rejected(raw, change):
    raw["info"].update(change)
    with pytest.raises(InvalidMatch):
        normalize(raw)


def test_remakes_duplicate_champions_and_bad_outcomes_rejected(raw):
    for field, value in (("gameEndedInEarlySurrender", True), ("championId", 2), ("win", False)):
        broken = copy.deepcopy(raw)
        broken["info"]["participants"][0][field] = value
        with pytest.raises(InvalidMatch):
            normalize(broken)


def test_region_queue_patch_filter(raw):
    for scope in ({"region": "NA1"}, {"queue": 440}, {"patches": ["16.19"]}):
        with pytest.raises(InvalidMatch):
            normalize(raw, **scope)


def test_match_id_deduplication_and_resumable_jsonl(tmp_path, raw):
    store = Store(tmp_path / "db")
    path = tmp_path / "SYNTHETIC.jsonl"
    path.write_text(json.dumps(raw) + "\n" + json.dumps(raw) + "\n{broken}\n")
    assert import_file(path, store)["imported"] == 1
    assert store.stats()["matches"] == 1
    second = import_file(path, store)
    assert second["imported"] == 0
    assert second["duplicate"] == 2
    assert second["rejected"] == 1


def test_single_json_and_array_import(tmp_path, raw):
    store = Store(tmp_path / "db")
    for name, value in (("single.json", raw), ("array.json", [raw, raw])):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        import_file(path, store)
    assert store.stats()["matches"] == 1


def test_match_queue_survives_reopening(tmp_path):
    store = Store(tmp_path)
    store.enqueue(["EUW1_1", "EUW1_1", "NA1_2"])
    assert store.pending("EUW1") == ["EUW1_1"]
    store.downloaded("EUW1_1")
    assert not Store(tmp_path).pending("EUW1")


def test_champion_numeric_key_is_not_display_name():
    data = parse_catalog({"data": {"Jinx": {"key": "222", "id": "Jinx", "name": "Jinx"},
                                     "MonkeyKing": {"key": "62", "id": "MonkeyKing", "name": "Wukong"}}}, "16.20.1")
    assert next(c for c in data["champions"] if c["name"] == "Wukong")["id"] == 62
    assert data["champions"][0]["id"] == 222
    assert "/16.20.1/" in data["champions"][0]["portrait"]
