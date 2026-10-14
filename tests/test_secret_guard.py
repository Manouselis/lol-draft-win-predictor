import importlib.util
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("secret_guard", Path(__file__).parents[1] / "scripts/check_secrets.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_packaged_private_file_and_embedded_key_are_blocked(tmp_path):
    key = b"RG" + b"API-" + b"00000000-0000-0000-0000-000000000001"
    archive = tmp_path / "SYNTHETIC-package.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("LeagueDraftLab/.env", b"SYNTHETIC_CONFIG")
        package.writestr("LeagueDraftLab/app.js", b"prefix" + key + b"suffix")
        package.writestr("LeagueDraftLab/README.txt", b"Safe public documentation")
    checked, findings = guard.scan(archive=archive)
    assert checked == 3
    assert set(findings) == {"LeagueDraftLab/.env", "LeagueDraftLab/app.js"}
    assert key.decode() not in str(findings)


def test_blank_template_is_allowed_but_private_runtime_artifacts_are_blocked():
    assert not guard.private_file(".env.example")
    for name in (".env", ".env.backup", "data/matches.sqlite3", "x/model.joblib", "logs/server.log", "lockfile"):
        assert guard.private_file(name)


def test_cpp_highs_symbols_are_not_github_tokens_but_standalone_tokens_are():
    assert not guard.contains_secret(b"_Z17highs_" + b"Symbol" * 10)
    assert guard.contains_secret(b"token=" + b"gh" + b"p_" + b"a" * 36 + b";")
