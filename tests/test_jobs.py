import threading

from loldraft.config import Config, now_ts
from loldraft.jobs import AutoTrainer
from loldraft.locking import exclusive
from loldraft.schemas import Settings
from loldraft.storage import Store


def scheduler(tmp_path, monkeypatch, *, count=50000, trainer=None):
    store = Store(tmp_path)
    monkeypatch.setattr(store, "stats", lambda *args: {"matches": count + 2000, "training_matches": count})
    config = Config(tmp_path)
    messages = []
    job = AutoTrainer(config, store, Settings(), trainer=trainer, progress=messages.append, clock=lambda: 100)
    return store, job, messages


def test_training_uses_29_day_readiness_not_30_day_count(tmp_path, monkeypatch):
    calls = []
    _, job, _ = scheduler(tmp_path, monkeypatch, count=49000, trainer=lambda *a, **kw: calls.append(1))
    assert not job.maybe_train()
    assert calls == []  # 51k recent records do not imply 50k trainable records.


def test_fresh_model_survives_collector_restart_without_retraining(tmp_path, monkeypatch):
    store, job, _ = scheduler(tmp_path, monkeypatch)
    store.set_meta("model", {"scope": {"region": "EUW1", "queue": 420, "patches": []},
                             "matches": 50000, "expires_at": now_ts() + 80000})
    assert not job.maybe_train()


def test_training_runs_without_blocking_the_collector(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def trainer(*args, **kwargs):
        entered.set()
        assert release.wait(5)
    _, job, _ = scheduler(tmp_path, monkeypatch, trainer=trainer)
    try:
        assert job.maybe_train()
        assert entered.wait(2)
        assert job.active
        assert not job.maybe_train(force=True)
    finally:
        release.set()
        job.finish()
    assert not job.active


def test_expiring_models_and_new_data_trigger_retraining(tmp_path, monkeypatch):
    for count, expiry in ((50000, now_ts() + 60), (75000, now_ts() + 80000)):
        calls = []
        store, job, _ = scheduler(tmp_path, monkeypatch, count=count,
                                  trainer=lambda *a, **kw: calls.append(1))
        store.set_meta("model", {"scope": {"region": "EUW1", "queue": 420, "patches": []},
                                 "matches": 50000, "expires_at": expiry})
        assert job.maybe_train()
        job.finish()
        assert calls == [1]


def test_failed_training_is_backed_off_and_does_not_abort_downloads(tmp_path, monkeypatch):
    def trainer(*args, **kwargs):
        raise ValueError("SYNTHETIC training failure")
    _, job, messages = scheduler(tmp_path, monkeypatch, trainer=trainer)
    assert job.maybe_train()
    job.finish()
    assert not job.maybe_train()
    assert messages == ["Automatic training deferred; collection continues. See training status."]


def test_running_external_training_is_respected(tmp_path, monkeypatch):
    store, job, _ = scheduler(tmp_path, monkeypatch)
    with exclusive(store.directory / "training.lock"):
        assert not job.maybe_train()
