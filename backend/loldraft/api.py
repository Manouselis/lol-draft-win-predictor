from __future__ import annotations

import asyncio
import json
import tempfile
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, SecretStr
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

from .champions import catalog
from .config import Config
from .locking import is_locked
from .runtime import Runtime
from .schemas import Draft, Settings

PROJECT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


class Mode(BaseModel):
    mode: str


class KeySetup(BaseModel):
    key: SecretStr


def create_app(config=None):
    config = config or Config.load()
    runtime = Runtime(config)

    @asynccontextmanager
    async def lifespan(app):
        monitor = asyncio.create_task(runtime.monitor.run())
        yield
        runtime.stop.set()
        monitor.cancel()
        try:
            await monitor
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="League Draft Lab", version="0.2.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runtime = runtime

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Fixed loopback bind + host/origin checks prevent drive-by sites from mutating local state.
        from starlette.responses import JSONResponse
        hostname = request.url.hostname
        test_client = request.client and request.client.host == "testclient"
        if hostname not in ("127.0.0.1", "localhost") and not (test_client and hostname == "testserver"):
            return JSONResponse({"detail": "Loopback host required"}, status_code=403)
        origin = request.headers.get("origin")
        if origin:
            from urllib.parse import urlparse
            try:
                parsed = urlparse(origin)
                trusted = (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
                           and parsed.port in (request.url.port, 8765, 5173))
            except ValueError:
                trusted = False
            if not trusted:
                return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
        if request.url.path == "/api/setup/key":
            if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                return JSONResponse({"detail": "JSON request required"}, status_code=415)
            if not secrets.compare_digest(request.headers.get("x-league-draft-token", ""), runtime.setup_token):
                return JSONResponse({"detail": "Open the local app to save a key"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https://ddragon.leagueoflegends.com data:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else "no-cache"
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "application": "LeagueDraftLab", "version": "0.2.0", "historical_window_days": 30}

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path == "/api/setup/key":
            from starlette.responses import JSONResponse
            return JSONResponse({"detail": "Provide the API key in the key field."}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @app.post("/api/setup/key")
    def setup_key(body: KeySetup):
        from .configuration import save_key, validate_key
        if is_locked(config.data_dir / "collection.lock"):
            raise HTTPException(409, "Stop collection before replacing the key")
        key = body.key.get_secret_value().strip()
        try:
            validate_key(key, runtime.settings.region)
            save_key(config, key)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        except OSError:
            raise HTTPException(409, "Cannot write the private profile here. Start the app from Windows Explorer.") from None
        return {"saved": True, "message": "Riot accepted the key. It is saved only in your local private profile."}

    @app.get("/api/state")
    def state():
        return runtime.state()

    @app.get("/api/events")
    async def events(request: Request):
        async def stream():
            previous = None
            while not await request.is_disconnected():
                payload = json.dumps(await asyncio.to_thread(runtime.state), separators=(",", ":"))
                if payload != previous:
                    yield "data: " + payload + "\n\n"
                    previous = payload
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(.5)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.post("/api/draft")
    def draft(draft: Draft):
        try:
            runtime.set_draft(draft)
            return runtime.state()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/draft/reset")
    def reset_draft():
        if runtime.mode == "live":
            raise HTTPException(409, "Switch to manual analysis before resetting")
        runtime.set_mode("manual")
        return runtime.state()

    @app.post("/api/mode")
    def mode(body: Mode):
        try:
            runtime.set_mode(body.mode)
            return runtime.state()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/champions")
    def champions():
        return catalog(config.data_dir)

    @app.post("/api/champions/refresh")
    def refresh_champions():
        return catalog(config.data_dir, refresh=True)

    @app.put("/api/settings")
    def settings(body: Settings):
        if runtime.job["status"] == "running" or any(
            is_locked(config.data_dir / name) for name in ("collection.lock", "training.lock")
        ):
            raise HTTPException(409, "Stop collection and wait for training to finish before changing data filters")
        runtime.settings = body
        runtime.store.set_meta("settings", body.model_dump())
        config.region, config.queue = body.region, body.queue
        runtime.set_mode("manual")
        runtime.cached_stats = None
        return runtime.state()

    @app.post("/api/train")
    def train_model():
        from .model import train
        try:
            runtime.start_job("train", lambda progress: train(runtime.store, runtime.settings,
                              minimum=config.min_matches, progress=progress))
            return {"status": "started"}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/collect")
    def collect_matches():
        from .cli import run_collection
        # Read an updated key without ever returning it to the browser.
        fresh = Config.load(env_file=config.env_file)
        config.riot_key = fresh.riot_key
        if not config.riot_key:
            raise HTTPException(409, "Set RIOT_API_KEY in .env, then retry")
        try:
            runtime.start_job("collect", lambda _: run_collection(config, runtime.store, runtime.settings,
                              stop=runtime.stop, auto_train=True))
            return {"status": "started"}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/jobs/stop")
    def stop_job():
        runtime.stop.set()
        (config.data_dir / "collection.stop").write_text("stop", encoding="utf-8")
        return {"status": "stopping", "detail": "Collector will save progress and stop. Training finishes safely."}

    @app.post("/api/import")
    async def import_matches(file: UploadFile = File(...)):
        from .ingestion import import_file
        if not file.filename or Path(file.filename).suffix.lower() not in (".json", ".jsonl", ".ndjson"):
            raise HTTPException(400, "Choose legally obtained Match-V5 JSON or JSONL")
        if runtime.job["status"] == "running":
            raise HTTPException(409, "Wait for the running task")
        imports = config.data_dir / "imports"
        imports.mkdir(exist_ok=True)
        temp = tempfile.NamedTemporaryFile(dir=imports, suffix=Path(file.filename).suffix, delete=False)
        path = Path(temp.name)
        size = 0
        try:
            with temp:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 2 * 1024 ** 3:
                        raise HTTPException(413, "Upload exceeds 2 GiB. Use the streaming CLI importer.")
                    temp.write(chunk)
            def run(progress):
                try:
                    return import_file(path, runtime.store, region=runtime.settings.region,
                                       queue=runtime.settings.queue, patches=runtime.settings.patches, progress=progress)
                finally:
                    path.unlink(missing_ok=True)
            runtime.start_job("import", run)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        return {"status": "started"}

    @app.post("/api/replay/{step}")
    def replay(step: int):
        fixtures = json.loads((PROJECT / "tests/fixtures/draft_sequence.json").read_text(encoding="utf-8"))
        if not 0 <= step < len(fixtures["sessions"]):
            raise HTTPException(400, "Replay step outside fixture sequence")
        runtime.replay(fixtures["sessions"][step])
        return {**runtime.state(), "fixture_notice": "Synthetic champion-select fixture; not a real live draft"}

    dist = PROJECT / "frontend/dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/favicon.svg")
        def favicon():
            return FileResponse(dist / "favicon.svg")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")
    return app
