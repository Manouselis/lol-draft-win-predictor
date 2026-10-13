from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from .config import Config, now_ts
from .locking import CancelSignal, exclusive
from .schemas import Settings
from .storage import Store


def run_collection(config, store, settings, *, stop=None, auto_train=False):
    from .jobs import AutoTrainer
    from .riot import collect
    automatic = AutoTrainer(config, store, settings) if auto_train else None

    def progress(message):
        store.set_meta("collection", {"status": "running", "message": message, "updated_at": now_ts()})
        print(message, flush=True)
        if automatic:
            automatic.maybe_train()

    with exclusive(config.data_dir / "collection.lock"):
        stop_path = config.data_dir / "collection.stop"
        stop_path.unlink(missing_ok=True)
        combined_stop = CancelSignal(stop or threading.Event(), stop_path)
        try:
            result = collect(store, settings, config.riot_key, stop=combined_stop, progress=progress)
            if automatic:
                automatic.maybe_train(force=True)
            store.set_meta("collection", {"status": "complete", "result": result, "updated_at": now_ts()})
            return result
        except Exception as exc:
            # Only our own sanitized API exceptions are exposed by the CLI.
            from .riot import RiotError
            message = str(exc) if isinstance(exc, (RiotError, ValueError)) else "Collection failed; see local diagnostics"
            store.set_meta("collection", {"status": "stopped", "message": message, "updated_at": now_ts()})
            raise RuntimeError(message) from None
        finally:
            if automatic:
                automatic.finish()


def main():
    parser = argparse.ArgumentParser(description="League Draft Lab: real recent data only")
    sub = parser.add_subparsers(dest="command", required=True)
    server = sub.add_parser("serve")
    server.add_argument("--port", type=int, default=8765)
    collector = sub.add_parser("collect")
    collector.add_argument("--auto-train", action="store_true")
    sub.add_parser("train")
    importer = sub.add_parser("import")
    importer.add_argument("path", type=Path)
    sub.add_parser("status")
    args = parser.parse_args()
    config = Config.load()
    store = Store(config.data_dir)
    settings = Settings.model_validate(store.get_meta("settings", {
        "region": config.region, "queue": config.queue, "target_matches": config.target_matches,
    }))
    if args.command == "serve":
        import uvicorn
        uvicorn.run("loldraft.api:create_app", factory=True, host="127.0.0.1", port=args.port, access_log=False)
    elif args.command == "collect":
        try:
            print(json.dumps(run_collection(config, store, settings, auto_train=args.auto_train), indent=2))
        except RuntimeError as exc:
            print(str(exc), flush=True)
            raise SystemExit(2) from None
    elif args.command == "train":
        from .model import train
        try:
            print(json.dumps(train(store, settings, minimum=config.min_matches, progress=print), indent=2))
        except ValueError as exc:
            print(str(exc))
            raise SystemExit(2) from None
    elif args.command == "import":
        from .ingestion import import_file
        print(json.dumps(import_file(args.path, store, region=settings.region, queue=settings.queue,
                                     patches=settings.patches, progress=print), indent=2))
    elif args.command == "status":
        print(json.dumps({"dataset": store.stats(settings.region, settings.queue, settings.patches),
                          "collection": store.get_meta("collection")}, indent=2))


if __name__ == "__main__":
    main()
