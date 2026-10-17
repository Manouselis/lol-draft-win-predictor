"""SYNTHETIC headless/migration checks, runnable without the ML dependency stack."""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts/pi/collector.py"


def test_collect_only_never_loads_model_or_numeric_dependencies(tmp_path):
    code = '''
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from loldraft.cli import run_collection
from loldraft.config import Config
from loldraft.schemas import Settings
from loldraft.storage import Store
import loldraft.riot
loldraft.riot.collect = lambda *a, **k: {"imported": 0}
run_collection(Config(data_dir=Path(sys.argv[2]), riot_key="SYNTHETIC_KEY"),
               Store(Path(sys.argv[2])), Settings(), auto_train=False)
assert not any(name in sys.modules for name in ("numpy", "scipy", "sklearn", "loldraft.model"))
print("COLLECTOR_ONLY_OK")
'''
    result = subprocess.run([sys.executable, "-c", code, str(ROOT / "backend"), str(tmp_path)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "COLLECTOR_ONLY_OK" in result.stdout


def test_status_never_echoes_the_private_key(tmp_path):
    private = tmp_path / ".env"
    private.write_text("RIOT_API_KEY=SYNTHETIC_PRIVATE_KEY\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(ENTRY), "--env-file", str(private),
                             "--data-dir", str(tmp_path / "data"), "status"],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "SYNTHETIC_PRIVATE_KEY" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["key_configured"] is True


def test_database_transfer_includes_wal_and_refuses_to_overwrite(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with sqlite3.connect(source / "matches.sqlite3") as active:
        active.execute("PRAGMA journal_mode=WAL")
        active.execute("CREATE TABLE progress (value INTEGER)")
        active.execute("INSERT INTO progress VALUES (17)")
        active.commit()
        destination = tmp_path / "snapshot.sqlite3"
        command = [sys.executable, str(ENTRY), "--env-file", str(tmp_path / ".env"),
                   "--data-dir", str(source), "backup", "--output", str(destination)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        if os.name != "nt":
            assert destination.stat().st_mode & 0o777 == 0o600
        with sqlite3.connect(destination) as snapshot:
            assert snapshot.execute("SELECT value FROM progress").fetchone()[0] == 17
        active.execute("UPDATE progress SET value=18")
        active.commit()
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        assert result.returncode != 0
        with sqlite3.connect(destination) as snapshot:
            assert snapshot.execute("SELECT value FROM progress").fetchone()[0] == 17
        assert active.execute("SELECT value FROM progress").fetchone()[0] == 18


@pytest.mark.skipif(os.name == "nt", reason="POSIX service SIGTERM is verified in Linux CI")
def test_service_sigterm_stops_cleanly_and_saves_progress(tmp_path):
    ready = tmp_path / "ready"
    data = tmp_path / "data"
    code = '''
import sys, runpy
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import loldraft.cli
entry, data, ready = sys.argv[2:5]
def collect(config, store, settings, *, stop, auto_train):
    assert auto_train is False
    Path(ready).touch()
    stop.wait(10)
    assert stop.is_set()
    store.set_meta("collection", {"status": "stopped", "message": "SYNTHETIC_SAVED"})
    raise RuntimeError("SYNTHETIC_CANCELLED")
loldraft.cli.run_collection = collect
sys.argv = [entry, "--env-file", str(Path(data).parent / ".env"), "--data-dir", data, "collect"]
runpy.run_path(entry, run_name="__main__")
'''
    process = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "backend"), str(ENTRY),
                                str(data), str(ready)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(.05)
        assert ready.exists()
        process.send_signal(signal.SIGTERM)
        output, error = process.communicate(timeout=5)
        assert process.returncode == 0, error
        assert "stopped safely" in output
        with sqlite3.connect(data / "matches.sqlite3") as db:
            progress = json.loads(db.execute("SELECT value FROM meta WHERE key='collection'").fetchone()[0])
        assert progress["status"] == "stopped"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
