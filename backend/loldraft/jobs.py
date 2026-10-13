from __future__ import annotations

import threading
import time

from .config import now_ts
from .locking import is_locked
from .model import train


class AutoTrainer:
    """Collect and train concurrently; existing artifact metadata survives collector restarts."""

    def __init__(self, config, store, settings, *, trainer=None, progress=None, clock=None):
        self.config, self.store, self.settings = config, store, settings.model_copy(deep=True)
        self.trainer = trainer or train
        self.progress = progress or (lambda message: print(message, flush=True))
        self.clock = clock or time.monotonic
        self.thread = None
        self.next_check = 0

    @property
    def active(self):
        return bool(self.thread and self.thread.is_alive())

    def maybe_train(self, *, force=False):
        if self.active or (not force and self.clock() < self.next_check):
            return False
        self.next_check = self.clock() + 30
        if is_locked(self.store.directory / "training.lock"):
            return False
        count = self.store.stats(self.settings.region, self.settings.queue, self.settings.patches)["training_matches"]
        if count < self.config.min_matches:
            return False
        metadata = self.store.get_meta("model")
        scope = {"region": self.settings.region, "queue": self.settings.queue,
                 "patches": sorted(self.settings.patches)}
        if metadata and metadata.get("scope") == scope:
            renewed_data = count >= metadata["matches"] + 25000
            expiring = metadata.get("expires_at", 0) <= now_ts() + 3600
            if not renewed_data and not expiring:
                return False
        # Delay a failed fit before retrying instead of reloading 50k records every ten downloads.
        self.next_check = self.clock() + 300

        def execute():
            try:
                self.trainer(self.store, self.settings, minimum=self.config.min_matches,
                             progress=self.progress)
            except Exception:
                # train() publishes a sanitized status; errors must not stop ingestion or expose credentials.
                self.progress("Automatic training deferred; collection continues. See training status.")
        self.thread = threading.Thread(target=execute, name="draft-auto-training", daemon=False)
        self.thread.start()
        return True

    def finish(self):
        if self.thread:
            self.thread.join()
