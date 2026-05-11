"""Phase E2 — BackupService create / peek / restore with atomicity + defence."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from npcreate_studio.services.backup_service import (
    SCHEMA_VERSION,
    BackupService,
)


def _service(tmp_path: Path, **kwargs) -> BackupService:
    return BackupService(
        tmp_path,
        app_name=kwargs.pop("app_name", "NP Create Studio"),
        app_version=kwargs.pop("app_version", "2.4.0"),
    )


def _seed_profiles(app_data: Path, payload: dict | None = None) -> Path:
    target = app_data / "device_profiles.json"
    target.write_text(
        json.dumps(payload or {"profiles": [{"name": "Redmi 13C"}]}),
        encoding="utf-8",
    )
    return target


# -- create ----------------------------------------------------------------


def test_create_backup_writes_zip_with_manifest_and_readme(tmp_path: Path):
    app_data = tmp_path / "data"
    app_data.mkdir()
    _seed_profiles(app_data)
    (app_data / "client_state.json").write_text('{"v": 1}', encoding="utf-8")

    svc = _service(app_data)
    out = tmp_path / "backup.zip"
    result = svc.create_backup(out)

    assert out.is_file()
    assert set(result.files) == {"device_profiles.json", "client_state.json"}
    assert result.manifest.schema == SCHEMA_VERSION
    assert result.manifest.app_version == "2.4.0"

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "README.txt" in names
        assert "device_profiles.json" in names
        assert "client_state.json" in names
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["schema"] == SCHEMA_VERSION
        assert manifest["app_name"] == "NP Create Studio"
        readme = zf.read("README.txt").decode("utf-8")
        assert "Restore" in readme


def test_create_backup_skips_missing_optional_files(tmp_path: Path):
    app_data = tmp_path / "data"
    app_data.mkdir()
    _seed_profiles(app_data)  # only profiles, no client_state

    svc = _service(app_data)
    result = svc.create_backup(tmp_path / "b.zip")
    assert result.files == ["device_profiles.json"]


def test_create_backup_never_includes_forbidden_filename(tmp_path: Path):
    app_data = tmp_path / "data"
    app_data.mkdir()
    _seed_profiles(app_data)
    (app_data / "tokens").write_bytes(b"SECRET TOKEN BLOB")
    (app_data / ".private_key").write_bytes(b"PRIVATE")

    svc = _service(app_data)
    # Forge an INCLUDE list that includes a forbidden filename — service
    # must still refuse to write it.
    svc.INCLUDE = ("device_profiles.json", "tokens", ".private_key")
    result = svc.create_backup(tmp_path / "b.zip")
    assert "tokens" not in result.files
    assert ".private_key" not in result.files
    with zipfile.ZipFile(tmp_path / "b.zip") as zf:
        assert "tokens" not in zf.namelist()
        assert ".private_key" not in zf.namelist()


def test_create_backup_creates_parent_dirs(tmp_path: Path):
    app_data = tmp_path / "data"
    app_data.mkdir()
    _seed_profiles(app_data)
    svc = _service(app_data)
    out = tmp_path / "nested" / "subdir" / "backup.zip"
    svc.create_backup(out)
    assert out.is_file()


# -- peek ------------------------------------------------------------------


def test_list_files_returns_zip_members(tmp_path: Path):
    app_data = tmp_path / "data"
    app_data.mkdir()
    _seed_profiles(app_data)
    svc = _service(app_data)
    out = svc.create_backup(tmp_path / "b.zip").path
    names = svc.list_files(out)
    assert "device_profiles.json" in names
    assert "manifest.json" in names


def test_list_files_returns_empty_for_missing_or_corrupt(tmp_path: Path):
    svc = _service(tmp_path)
    assert svc.list_files(tmp_path / "nope.zip") == []
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    assert svc.list_files(bad) == []


def test_read_manifest_parses_back_what_create_wrote(tmp_path: Path):
    app_data = tmp_path / "data"
    app_data.mkdir()
    _seed_profiles(app_data)
    svc = _service(app_data, app_version="2.5.1")
    out = svc.create_backup(tmp_path / "b.zip").path
    manifest = svc.read_manifest(out)
    assert manifest is not None
    assert manifest.schema == SCHEMA_VERSION
    assert manifest.app_version == "2.5.1"
    assert "device_profiles.json" in manifest.files


def test_read_manifest_returns_none_for_missing_manifest(tmp_path: Path):
    svc = _service(tmp_path)
    fake = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(fake, "w") as zf:
        zf.writestr("device_profiles.json", b"{}")
    assert svc.read_manifest(fake) is None


def test_read_manifest_returns_none_for_corrupt_zip(tmp_path: Path):
    svc = _service(tmp_path)
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"definitely not a zip")
    assert svc.read_manifest(bad) is None


def test_read_manifest_returns_none_for_non_dict_payload(tmp_path: Path):
    svc = _service(tmp_path)
    fake = tmp_path / "weird.zip"
    with zipfile.ZipFile(fake, "w") as zf:
        zf.writestr("manifest.json", b"[1, 2, 3]")
    assert svc.read_manifest(fake) is None


# -- restore ---------------------------------------------------------------


def test_restore_roundtrip(tmp_path: Path):
    src = tmp_path / "src_data"
    src.mkdir()
    profile_payload = {"profiles": [{"name": "Redmi 13C", "model": "23100RN82L"}]}
    _seed_profiles(src, profile_payload)
    (src / "client_state.json").write_text('{"last_video": "/tmp/x.mp4"}', encoding="utf-8")

    svc_src = _service(src)
    backup_zip = svc_src.create_backup(tmp_path / "b.zip").path

    dst = tmp_path / "dst_data"
    dst.mkdir()
    svc_dst = BackupService(dst, app_name="NP Create Studio", app_version="2.4.0")
    restored = svc_dst.restore_backup(backup_zip)
    assert set(restored) == {"device_profiles.json", "client_state.json"}

    written = json.loads((dst / "device_profiles.json").read_text(encoding="utf-8"))
    assert written == profile_payload


def test_restore_refuses_unknown_schema(tmp_path: Path):
    fake = tmp_path / "future.zip"
    with zipfile.ZipFile(fake, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "schema": 99,
            "app_name": "NP Create Studio",
            "app_version": "9.9.9",
            "created_at": "2099-01-01T00:00:00",
            "files": [],
        }))
        zf.writestr("device_profiles.json", b"{}")
    svc = _service(tmp_path)
    with pytest.raises(ValueError, match="schema"):
        svc.restore_backup(fake)


def test_restore_refuses_missing_manifest(tmp_path: Path):
    bad = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("device_profiles.json", b"{}")
    svc = _service(tmp_path)
    with pytest.raises(ValueError, match="manifest"):
        svc.restore_backup(bad)


def test_restore_drops_forbidden_filenames_at_any_depth(tmp_path: Path):
    app_data = tmp_path / "data"
    app_data.mkdir()
    forge = tmp_path / "forge.zip"
    with zipfile.ZipFile(forge, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "schema": SCHEMA_VERSION,
            "app_name": "NP Create Studio",
            "app_version": "2.4.0",
            "created_at": "2026-05-11T00:00:00",
            "files": ["device_profiles.json", "nested/.private_key", "tokens"],
        }))
        zf.writestr("device_profiles.json", b"{}")
        zf.writestr("nested/.private_key", b"SHOULD NEVER LAND")
        zf.writestr("tokens", b"SHOULD ALSO NEVER LAND")
    svc = _service(app_data)
    restored = svc.restore_backup(forge)
    assert "device_profiles.json" in restored
    assert "nested/.private_key" not in restored
    assert "tokens" not in restored
    assert not (app_data / "nested" / ".private_key").exists()
    assert not (app_data / "tokens").exists()


def test_restore_skips_path_traversal_entries(tmp_path: Path):
    app_data = tmp_path / "data"
    app_data.mkdir()
    # Pre-existing victim file outside app_data — must remain untouched.
    victim = tmp_path / "victim.txt"
    victim.write_text("safe", encoding="utf-8")

    forge = tmp_path / "evil.zip"
    # Have to bypass zipfile's name validation; manually craft the entry.
    with zipfile.ZipFile(forge, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "schema": SCHEMA_VERSION,
            "app_name": "x", "app_version": "0", "created_at": "x",
            "files": ["device_profiles.json"],
        }))
        zf.writestr("device_profiles.json", b"{}")
        info = zipfile.ZipInfo("../victim.txt")
        zf.writestr(info, b"PWNED")

    svc = _service(app_data)
    restored = svc.restore_backup(forge)
    assert restored == ["device_profiles.json"]
    assert victim.read_text(encoding="utf-8") == "safe"


def test_restore_does_not_touch_install_when_zip_is_corrupt(tmp_path: Path):
    app_data = tmp_path / "data"
    app_data.mkdir()
    pre_existing = app_data / "device_profiles.json"
    pre_existing.write_text("ORIGINAL", encoding="utf-8")

    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip file")
    svc = _service(app_data)
    with pytest.raises(ValueError):
        svc.restore_backup(bad)
    assert pre_existing.read_text(encoding="utf-8") == "ORIGINAL"


def test_restore_handles_cross_filesystem_via_copy_fallback(tmp_path: Path, monkeypatch):
    app_data = tmp_path / "data"
    app_data.mkdir()
    _seed_profiles(app_data)
    svc = _service(app_data)
    backup_zip = svc.create_backup(tmp_path / "b.zip").path

    dst = tmp_path / "dst"
    dst.mkdir()
    svc_dst = BackupService(dst, app_name="X", app_version="1.0.0")

    # Force os.replace to raise so we exercise the copy fallback.
    original_replace = Path.replace

    def boom(self, target):  # type: ignore[no-redef]
        raise OSError("cross-device link not permitted")

    monkeypatch.setattr(Path, "replace", boom)
    try:
        restored = svc_dst.restore_backup(backup_zip)
    finally:
        monkeypatch.setattr(Path, "replace", original_replace)
    assert "device_profiles.json" in restored
    assert (dst / "device_profiles.json").is_file()


# -- filename helper -------------------------------------------------------


def test_suggest_filename_includes_version_and_timestamp(tmp_path: Path):
    svc = _service(tmp_path, app_version="2.4.0")
    name = svc.suggest_filename(now=1715472000)  # fixed UTC moment
    assert name.startswith("npcreate-backup-v2.4.0-")
    assert name.endswith(".zip")


def test_suggest_filename_sanitizes_unsafe_version_chars(tmp_path: Path):
    svc = _service(tmp_path, app_version="2.4.0/evil")
    name = svc.suggest_filename(now=1715472000)
    assert "/" not in name
    assert name.startswith("npcreate-backup-v2.4.0-evil-")
