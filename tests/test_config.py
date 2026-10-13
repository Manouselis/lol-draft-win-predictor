from loldraft.config import Config


def test_renewed_key_is_read_without_stale_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIOT_API_KEY", "SYNTHETIC_OLD_ENV")
    path = tmp_path / ".env"
    path.write_text("RIOT_API_KEY=SYNTHETIC_LOCAL_FIRST\nLOL_MIN_MATCHES=1\n", encoding="utf-8-sig")
    assert Config.load().riot_key.startswith("SYNTHETIC_"), "Configuration must use the test-local file"
    assert Config.load().riot_key == "SYNTHETIC_LOCAL_FIRST"
    assert Config.load().min_matches == 50000
    path.write_text("RIOT_API_KEY=SYNTHETIC_RENEWED\n")
    assert Config.load().riot_key == "SYNTHETIC_RENEWED"
