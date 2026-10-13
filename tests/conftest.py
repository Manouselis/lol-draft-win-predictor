"""All data produced here is SYNTHETIC and confined to temporary test directories."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from loldraft.config import Config, ROLES, now_ts
from loldraft.ingestion import normalize
from loldraft.model import train
from loldraft.schemas import Settings
from loldraft.storage import Store


def synthetic_raw(index=1, *, age_days=2, blue_win=True):
    started = (now_ts() - int(age_days * 86400)) * 1000
    return {
        "metadata": {"matchId": f"EUW1_{90000000 + index}", "participants": ["SYNTHETIC_PUUID"]},
        "info": {"gameStartTimestamp": started, "gameCreation": started, "gameDuration": 1800,
                 "gameVersion": "16.20.123.456", "queueId": 420, "mapId": 11,
                 "gameMode": "CLASSIC", "gameType": "MATCHED_GAME",
                 "participants": [
                     {"teamId": team_id, "championId": k + 1 + (0 if team_id == 100 else 5),
                      "teamPosition": role, "win": blue_win if team_id == 100 else not blue_win,
                      "puuid": "SYNTHETIC_PRIVATE_FIELD", "riotIdGameName": "SYNTHETIC_NAME"}
                     for team_id in (100, 200) for k, role in enumerate(ROLES)
                 ]}
    }


@pytest.fixture
def raw():
    return copy.deepcopy(synthetic_raw())


@pytest.fixture
def sessions():
    path = Path(__file__).parent / "fixtures/draft_sequence.json"
    return json.loads(path.read_text())["sessions"]


@pytest.fixture(scope="session")
def trained(tmp_path_factory):
    directory = tmp_path_factory.mktemp("SYNTHETIC-model-test")
    store = Store(directory)
    rng = np.random.default_rng(123)
    for i in range(600):
        raw = synthetic_raw(i, age_days=27 - i / 600 * 26)
        ids = rng.choice(np.arange(1, 31), size=10, replace=False)
        signal = .35 + sum(1.0 if c <= 6 else -.3 if c >= 25 else 0 for c in ids[:5]) - sum(1.0 if c <= 6 else -.3 if c >= 25 else 0 for c in ids[5:])
        outcome = bool(rng.random() < 1 / (1 + np.exp(-signal)))
        for j, p in enumerate(raw["info"]["participants"]):
            p["championId"] = int(ids[j])
            p["win"] = outcome if j < 5 else not outcome
        store.insert(normalize(raw))
    report = train(store, Settings(), minimum=300)
    return directory, store, report


@pytest.fixture
def config(tmp_path):
    return Config(data_dir=tmp_path / "data")
