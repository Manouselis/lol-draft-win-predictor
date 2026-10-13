from __future__ import annotations

import threading
import time

from .config import now_ts
from .lcu import LcuMonitor, parse_session
from .locking import is_locked
from .model import Predictor
from .schemas import Draft, Settings
from .storage import Store


class Runtime:
    def __init__(self, config):
        self.config = config
        self.store = Store(config.data_dir)
        self.settings = Settings.model_validate(self.store.get_meta("settings", {
            "region": config.region, "queue": config.queue, "target_matches": config.target_matches,
        }))
        self.draft = Draft(region=self.settings.region, queue=self.settings.queue)
        self.mode = "manual"
        self.history = []
        self.last_signature = None
        self.last_result = None
        self.prediction_key = None
        self.lock = threading.RLock()
        self.predictor = Predictor(config.data_dir)
        self.monitor = LcuMonitor(config, self.live_update)
        self.job = {"status": "idle", "kind": None, "message": ""}
        self.stop = threading.Event()
        self.cached_stats = None
        self.stats_time = 0

    def live_update(self, draft, reset=False):
        with self.lock:
            if self.mode == "live":
                if reset:
                    self.history = []
                    self.last_signature = None
                self.draft = draft or Draft(side="unknown", region=self.settings.region, queue=self.settings.queue)

    def set_draft(self, draft):
        with self.lock:
            if self.mode == "live":
                raise ValueError("Switch to manual mode to edit picks")
            self.draft = draft

    def set_mode(self, mode):
        if mode not in ("manual", "live", "replay"):
            raise ValueError("Unsupported mode")
        if mode == "live" and not (self.config.lcu_enabled and self.config.riot_live_approved):
            raise ValueError("Live mode requires Riot review of this exact use case and local opt-in. See docs/compliance.md.")
        with self.lock:
            self.mode = mode
            self.history = []
            self.last_signature = None
            self.draft = Draft(region=self.settings.region, queue=self.settings.queue,
                               side="unknown" if mode == "live" else "blue")

    def replay(self, session):
        with self.lock:
            if self.mode != "replay":
                self.set_mode("replay")
            self.draft = parse_session(session, region=self.settings.region, queue=self.settings.queue)

    def state(self):
        with self.lock:
            self.predictor.reload()
            cache_key = (self.draft.model_dump_json(), self.predictor.stamp, now_ts() // 2)
            if cache_key != self.prediction_key:
                self.last_result = (self.predictor.predict(self.draft), self.predictor.predict(self.draft, include_hovers=False))
                self.prediction_key = cache_key
            prediction, confirmed = self.last_result
            signature = self.draft.model_dump_json() + ":" + str(prediction.get("version")) + str(prediction["ready"])
            if signature != self.last_signature:
                before = self.history[-1]["probability"] if self.history else None
                probability = prediction["probability"]
                self.history.append({"time": now_ts(), "probability": probability,
                                     "confirmed": confirmed["probability"],
                                     "known": sum(bool(p.champion_id) for p in self.draft.allies + self.draft.enemies),
                                     "tentative": prediction.get("tentative", False),
                                     "change": probability - before if probability is not None and before is not None else None})
                self.history = self.history[-80:]
                self.last_signature = signature
            if self.cached_stats is None or time.monotonic() - self.stats_time > 5:
                self.cached_stats = self.store.stats(self.settings.region, self.settings.queue, self.settings.patches)
                self.stats_time = time.monotonic()
            self.predictor.reload()
            metadata = self.predictor.artifact["metadata"] if self.predictor.artifact else self.store.get_meta("model")
            collection = self.store.get_meta("collection")
            if collection and collection["status"] == "running" and not is_locked(self.config.data_dir / "collection.lock"):
                collection = {**collection, "status": "interrupted", "message": "Collector stopped; resume to continue saved downloads."}
            training = self.store.get_meta("training")
            if (training and training["status"] == "running" and now_ts() - training.get("updated_at", 0) > 3
                    and not is_locked(self.config.data_dir / "training.lock")):
                training = {**training, "status": "interrupted", "message": "Training interrupted; the previous artifact was preserved."}
            return {"draft": self.draft.model_dump(), "mode": self.mode, "prediction": prediction,
                    "confirmed": confirmed, "history": self.history, "dataset": self.cached_stats,
                    "model": metadata, "settings": self.settings.model_dump(), "job": self.job.copy(),
                    "collection": collection, "training": training,
                    "integration": {"status": self.monitor.status, "message": self.monitor.message,
                                    "client_detected": self.monitor.available,
                                    "live_enabled": self.config.lcu_enabled and self.config.riot_live_approved},
                    "api_key_configured": bool(self.config.riot_key), "minimum_matches": self.config.min_matches}

    def start_job(self, kind, function):
        with self.lock:
            if self.job["status"] == "running":
                raise ValueError("A background task is already running")
            self.stop.clear()
            self.job = {"status": "running", "kind": kind, "message": "Starting…"}
        def progress(message):
            with self.lock:
                self.job["message"] = message
        def execute():
            try:
                result = function(progress)
                with self.lock:
                    self.job.update(status="complete", result=result, message="Task complete")
            except Exception as exc:
                from .riot import RiotError
                with self.lock:
                    self.job.update(status="failed", message=str(exc) if isinstance(exc, (RiotError, ValueError, RuntimeError))
                                    else "Task failed. Check input format and local configuration.")
            finally:
                self.cached_stats = None
        threading.Thread(target=execute, daemon=True, name=f"draft-{kind}").start()
