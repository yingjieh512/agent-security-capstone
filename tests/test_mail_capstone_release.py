"""Release checks for drift detection, safe provisioning and the portable archive."""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import package_mail_capstone as bundle
import reproduce_mail_capstone as reproduce


def test_semantic_diff_reports_location_and_preserves_json_types():
    assert reproduce.first_difference({"a": 1, "b": 2}, {"b": 2, "a": 1}) is None
    assert reproduce.first_difference({"x": [0, True]}, {"x": [0, 1]}).startswith("$.x[1]")
    assert "extra ['body']" in reproduce.first_difference({"grant": {}}, {"grant": {"body": "abc"}})


def test_offline_installer_rejects_wrong_checksum_without_overwriting_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "mailpit").write_bytes(b"existing")
    bad = tmp_path / "download.tar.gz"
    bad.write_bytes(b"not the release")
    monkeypatch.setattr(reproduce, "CACHE", cache)
    monkeypatch.setattr(reproduce, "ARCHIVE_SHA256", {
        (reproduce.platform.system(), reproduce.platform.machine()): ("fixture", "0" * 64)})
    with pytest.raises(ValueError, match="SHA-256"):
        reproduce.install_archive(bad)
    assert (cache / "mailpit").read_bytes() == b"existing"


def test_bundle_manifest_matches_bytes_and_excludes_machine_state(tmp_path, monkeypatch):
    files = {"LICENSE": "license", "examples/mail_audit/input.json": "{}", "scripts/frozen.py": "pass\n"}
    pin = hashlib.sha256(files["scripts/frozen.py"].encode()).hexdigest()
    files[bundle.FREEZE] = json.dumps({"files": {"scripts/frozen.py": pin}})
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (tmp_path / "examples/mail_audit/private.json").write_text("private")
    monkeypatch.setattr(bundle, "ROOT", tmp_path)
    monkeypatch.setattr(bundle, "PROJECT_FILES", ("LICENSE", "examples/mail_audit/input.json", bundle.FREEZE))
    first, second = tmp_path/"release.zip", tmp_path/"again.zip"
    bundle.package(first)
    bundle.package(second)
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        names = {p.removeprefix(bundle.PREFIX) for p in archive.namelist()}
        assert names == set(files) | {"README.md", "SHA256SUMS"}
        for line in archive.read(bundle.PREFIX + "SHA256SUMS").decode().splitlines():
            sha, name = line.split("  ", 1)
            assert sha == hashlib.sha256(archive.read(bundle.PREFIX + name)).hexdigest()
    (tmp_path / "scripts/frozen.py").write_text("changed")
    with pytest.raises(ValueError, match="Frozen input changed"):
        bundle.package(first)
    assert first.read_bytes() == second.read_bytes()
