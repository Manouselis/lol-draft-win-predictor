"""User-facing launcher for source checkouts and the self-contained Windows bundle."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .config import Config, private_state_dir


def local_request(url, *, post=False):
    request = urllib.request.Request(url, data=b"" if post else None,
                                     headers={"Origin": url.rsplit("/api/", 1)[0]})
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.load(response)


def child_command(config, port):
    entry = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "loldraft.desktop"]
    return entry + ["--serve", "--port", str(port), "--env-file", str(config.env_file),
                    "--data-dir", str(config.data_dir)]


def verify_ml_runtime():
    """Exercise bundled native ML libraries in memory; never publish a test model."""
    import io
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from .features import HASHER
    from .model import metrics
    matrix = HASHER.transform([{"SYNTHETIC_A": float(i % 2), "SYNTHETIC_B": 1.0} for i in range(200)])
    outcomes = np.asarray([i % 2 for i in range(200)])
    model = LogisticRegression(solver="liblinear", C=.1).fit(matrix, outcomes)
    logits = model.decision_function(matrix).reshape(-1, 1)
    calibrator = LogisticRegression().fit(logits, outcomes)
    buffer = io.BytesIO()
    joblib.dump((model, calibrator), buffer)
    buffer.seek(0)
    loaded, calibrated = joblib.load(buffer)
    probabilities = calibrated.predict_proba(loaded.decision_function(matrix).reshape(-1, 1))[:, 1]
    assert metrics(outcomes, probabilities)["matches"] == 200
    return {"sparse_model_fit": True, "calibration": True, "serialization_roundtrip": True,
            "metrics": True, "test_model_published": False}


def launch(config, *, port=8765, collect=False, browser=True):
    url = f"http://127.0.0.1:{port}"
    try:
        health = local_request(url + "/api/health")
    except (OSError, ValueError):
        health = None
    if health and (health.get("application") != "LeagueDraftLab" or health.get("version") != "0.2.1"):
        raise RuntimeError("An older app is using port 8765. Close its server window, then start again.")
    if health is None:
        logs = config.env_file.parent / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "desktop-server.log").open("a", encoding="utf-8") as output:
            subprocess.Popen(child_command(config, port), stdin=subprocess.DEVNULL,
                             stdout=output, stderr=output,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                             start_new_session=os.name != "nt")
        for _ in range(100):
            try:
                health = local_request(url + "/api/health")
                break
            except (OSError, ValueError):
                time.sleep(.2)
        if health is None:
            raise RuntimeError("The local app did not start. See the private logs/desktop-server.log file.")
    state = local_request(url + "/api/state")
    actual = state.get("configuration", {}).get("database")
    expected = str(config.data_dir / "matches.sqlite3")
    if not actual or os.path.normcase(os.path.abspath(actual)) != os.path.normcase(os.path.abspath(expected)):
        raise RuntimeError("Another project is already open on port 8765. Close its server before opening this project.")
    interrupted = (state.get("collection") or {}).get("status") == "interrupted"
    if (collect or interrupted) and state["api_key_configured"]:
        if (state.get("collection") or {}).get("status") != "running":
            local_request(url + "/api/collect", post=True)
    if browser:
        webbrowser.open(url + ("?setup=1" if not state["api_key_configured"] else ""))
    return {"url": url, "database": actual, "key_configured": state["api_key_configured"]}


def main():
    parser = argparse.ArgumentParser(description="Open League Draft Lab")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--diagnose", type=Path, metavar="REPORT_PATH")
    parser.add_argument("--verify-runtime", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.verify_runtime:
        args.verify_runtime.write_text(json.dumps(verify_ml_runtime()), encoding="utf-8")
        return
    config = Config.load(env_file=args.env_file or private_state_dir() / ".env")
    if args.data_dir:
        config.data_dir = args.data_dir.resolve()
    if args.diagnose:
        args.diagnose.write_text(json.dumps({"database": str(config.data_dir / "matches.sqlite3"),
                                            "env_file": str(config.env_file),
                                            "key_configured": bool(config.riot_key)}), encoding="utf-8")
        return
    if args.serve:
        logs = config.env_file.parent / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        if getattr(sys, "frozen", False):
            sys.stdout = sys.stderr = (logs / "desktop-server.log").open("a", encoding="utf-8", buffering=1)
        import uvicorn
        from .api import create_app
        app = create_app(config)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, access_log=False))
        app.state.shutdown_callback = lambda: setattr(server, "should_exit", True)
        server.run()
    else:
        launch(config, port=args.port, collect=args.collect, browser=not args.no_browser)


if __name__ == "__main__":
    main()
