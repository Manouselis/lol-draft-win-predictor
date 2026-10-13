import copy

import joblib
import numpy as np
import pytest

from loldraft.config import now_ts
from loldraft.features import features, masked
from loldraft.model import Predictor, train, wilson
from loldraft.schemas import Draft, Pick, Settings
from loldraft.storage import Store


def test_missing_or_corrupt_model_never_fabricates_probability(tmp_path):
    model = Predictor(tmp_path)
    assert model.predict(Draft())["probability"] is None
    (tmp_path / "model.joblib").write_bytes(b"bad model")
    assert model.predict(Draft())["ready"] is False


def test_insufficient_real_data_blocks_training(tmp_path):
    with pytest.raises(ValueError, match="Model not ready"):
        train(Store(tmp_path), Settings())
    assert not (tmp_path / "model.joblib").exists()


def test_failed_retraining_preserves_the_existing_artifact(tmp_path, trained):
    import shutil
    path = tmp_path / "model.joblib"
    shutil.copyfile(trained[0] / "model.joblib", path)
    original = path.read_bytes()
    store = Store(tmp_path)
    with pytest.raises(ValueError, match="Model not ready"):
        train(store, Settings())
    assert path.read_bytes() == original
    assert store.get_meta("training")["status"] == "failed"
    assert Predictor(tmp_path).predict(Draft())["ready"]


def test_training_masks_never_insert_unknown_champions(trained):
    _, store, _ = trained
    match = store.recent()[0]
    blue, red = masked(match, total=2)
    values = features(blue, red, "EUW1", 420, "16.20")
    visible = {c for c, _ in blue + red}
    assert sum(k.startswith("champion:") for k in values) == 2
    assert all(int(k.split(":")[1]) in visible for k in values if k.startswith("champion:"))
    changed = copy.deepcopy(match)
    for color, picks in (("blue", blue), ("red", red)):
        revealed = {c for c, _ in picks}
        for p in changed[color]:
            if p["champion_id"] not in revealed:
                p["champion_id"] = 999
    assert masked(changed, total=2) == (blue, red)


def test_empty_draft_uses_learned_historical_baseline(trained):
    directory, _, report = trained
    result = Predictor(directory).predict(Draft())
    assert result["ready"]
    assert result["probability"] == pytest.approx(report["report"]["baseline_blue_win_rate"])
    assert result["probability"] != .5


def test_partial_probabilities_change_and_reload_consistently(trained):
    directory, _, _ = trained
    predictor = Predictor(directory)
    draft = Draft()
    probabilities = [predictor.predict(draft)["probability"]]
    for i, cid in enumerate([1, 2, 3, 4, 5]):
        draft.allies[i] = Pick(champion_id=cid, state="locked")
        probabilities.append(predictor.predict(draft)["probability"])
    assert all(0 < p < 1 for p in probabilities)
    assert len(set(round(p, 7) for p in probabilities)) > 1
    assert predictor.predict(draft)["probability"] == Predictor(directory).predict(draft)["probability"]


def test_side_orientation_preserves_complement(trained):
    directory, _, _ = trained
    model = Predictor(directory)
    blue = [Pick(champion_id=c, state="locked") for c in range(1, 6)]
    red = [Pick(champion_id=c, state="locked") for c in range(11, 16)]
    a = model.predict(Draft(allies=blue, enemies=red, side="blue"))["probability"]
    b = model.predict(Draft(allies=red, enemies=blue, side="red"))["probability"]
    assert a + b == pytest.approx(1)


def test_hovers_are_separate_from_confirmed(trained):
    model = Predictor(trained[0])
    draft = Draft(allies=[Pick(champion_id=1, state="hover")] + [Pick() for _ in range(4)])
    tentative, confirmed = model.predict(draft), model.predict(draft, include_hovers=False)
    assert tentative["tentative"]
    assert tentative["known"] == 1
    assert confirmed["known"] == 0
    assert tentative["probability"] != confirmed["probability"]


def test_all_36_partial_team_sizes_supported(trained):
    model = Predictor(trained[0])
    for ally_count in range(6):
        for enemy_count in range(6):
            allies = [Pick(champion_id=i + 1, state="locked") for i in range(ally_count)]
            enemies = [Pick(champion_id=i + 11, state="locked") for i in range(enemy_count)]
            draft = Draft(allies=allies + [Pick() for _ in range(5 - ally_count)],
                          enemies=enemies + [Pick() for _ in range(5 - enemy_count)])
            result = model.predict(draft)
            assert result["ready"]
            assert result["known"] == ally_count + enemy_count
            assert 0 < result["probability"] < 1


def test_unsupported_regions_queues_patches_and_champions_not_guessed(trained):
    model = Predictor(trained[0])
    for draft in (Draft(region="NA1"), Draft(queue=440), Draft(patch="1.1"),
                  Draft(allies=[Pick(champion_id=999, state="locked")] + [Pick() for _ in range(4)])):
        assert model.predict(draft)["probability"] is None


def test_temporal_splits_and_validation_metrics(trained):
    _, store, meta = trained
    report = meta["report"]
    assert store.get_meta("training")["status"] == "complete"
    assert meta["scope"] == {"region": "EUW1", "queue": 420, "patches": []}
    assert report["split"] == {"training": 540, "calibration": 30, "test": 30}
    a, b = report["boundaries"].values()
    assert a < b
    rows = store.recent()
    assert len({m["match_id"] for m in rows}) == len(rows)
    assert sum(report["split"].values()) == report["unique_matches"]
    for n in ("0", "2", "4", "6", "8", "10"):
        group = report["groups"][n]
        assert np.isfinite(group["model"]["brier"])
        assert 0 <= group["model"]["brier"] <= 1
        assert np.isfinite(group["model"]["log_loss"])
        assert 0 <= group["model"]["ece"] <= 1
        assert group["model"]["matches"] == report["split"]["test"]


def test_new_patch_can_fit_without_using_later_calibration_or_test_matches(tmp_path, trained):
    store = Store(tmp_path)
    for index, match in enumerate(trained[1].recent()):
        match["patch"] = "16.19" if index < 480 else "16.20"
        store.insert(match)
    meta = train(store, Settings(), minimum=300)
    assert meta["patches"] == {"16.19": 480, "16.20": 60}
    first, second = meta["report"]["boundaries"].values()
    rows = store.recent()
    fit = [m for m in rows if m["started_at"] < first]
    calibration = [m for m in rows if first <= m["started_at"] < second]
    test = [m for m in rows if m["started_at"] >= second]
    assert max(m["started_at"] for m in fit) < min(m["started_at"] for m in calibration)
    assert max(m["started_at"] for m in calibration) < min(m["started_at"] for m in test)
    assert Predictor(tmp_path).predict(Draft(patch="16.20"))["ready"]


def test_expired_and_synthetic_models_rejected(tmp_path, trained):
    artifact = joblib.load(trained[0] / "model.joblib")
    artifact["metadata"]["expires_at"] = now_ts() - 1
    joblib.dump(artifact, tmp_path / "model.joblib")
    assert Predictor(tmp_path).predict(Draft())["ready"] is False
    artifact["metadata"]["synthetic"] = True
    artifact["metadata"]["expires_at"] = now_ts() + 100
    joblib.dump(artifact, tmp_path / "model.joblib")
    assert Predictor(tmp_path).predict(Draft())["ready"] is False


def test_uncertainty_bounds():
    assert wilson(0, 0) == [0, 1]
    lo, hi = wilson(60, 100)
    assert 0 <= lo < .6 < hi <= 1
