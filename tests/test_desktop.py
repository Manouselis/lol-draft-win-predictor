import pytest

from loldraft.desktop import launch


@pytest.mark.parametrize("status", ["interrupted", "stopped", "running"])
def test_opening_app_only_resumes_an_interrupted_collection(config, monkeypatch, status):
    requests = []
    def local(url, *, post=False):
        requests.append((url, post))
        if url.endswith("/api/health"):
            return {"application": "LeagueDraftLab", "version": "0.2.1"}
        if url.endswith("/api/state"):
            return {"configuration": {"database": str(config.data_dir / "matches.sqlite3")},
                    "collection": {"status": status}, "api_key_configured": True}
        return {"status": "started"}
    monkeypatch.setattr("loldraft.desktop.local_request", local)
    launch(config, browser=False)
    assert any(url.endswith("/api/collect") for url, _ in requests) == (status == "interrupted")


def test_collect_shortcut_explicitly_resumes_saved_stopped_collection(config, monkeypatch):
    requests = []
    def local(url, *, post=False):
        requests.append(url)
        if url.endswith("/api/health"):
            return {"application": "LeagueDraftLab", "version": "0.2.1"}
        if url.endswith("/api/state"):
            return {"configuration": {"database": str(config.data_dir / "matches.sqlite3")},
                    "collection": {"status": "stopped"}, "api_key_configured": True}
        return {"status": "started"}
    monkeypatch.setattr("loldraft.desktop.local_request", local)
    launch(config, collect=True, browser=False)
    assert requests[-1].endswith("/api/collect")


def test_launcher_refuses_to_reuse_another_projects_database(config, monkeypatch, tmp_path):
    def local(url, **_kwargs):
        if url.endswith("/api/health"):
            return {"application": "LeagueDraftLab", "version": "0.2.1"}
        return {"configuration": {"database": str(tmp_path / "another-project/matches.sqlite3")},
                "collection": {"status": "interrupted"}, "api_key_configured": True}
    monkeypatch.setattr("loldraft.desktop.local_request", local)
    with pytest.raises(RuntimeError, match="Another project"):
        launch(config, browser=False)
