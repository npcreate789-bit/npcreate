"""Phase N — LSPatchService unit tests (no real adb / lspatch.jar required)."""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from npcreate_studio.services.lspatch_service import (
    TIKTOK_PACKAGES,
    LSPatchService,
)


@dataclass
class _CmdResult:
    """Stand-in for `npcreate_studio.infrastructure.subprocess_runner.CommandResult`.

    Only the three fields LSPatchService reads (returncode, stdout, stderr)
    are required."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class _FakeAdb:
    """In-memory adb double. Routes ``exec_argv("shell", "<cmd>", ...)``
    through a settable dict and records every call for assertions."""

    def __init__(self) -> None:
        self.shell_responses: dict[str, str] = {}
        self.argv_responses: dict[tuple, _CmdResult] = {}
        self.calls: list[tuple] = []
        self.available = True

    def is_available(self) -> bool:
        return self.available

    def exec_argv(self, *args, serial=None, timeout: float = 10.0):
        self.calls.append(args)
        if args and args[0] == "shell":
            cmd = args[1] if len(args) > 1 else ""
            for prefix, response in self.shell_responses.items():
                if cmd.startswith(prefix):
                    return _CmdResult(stdout=response)
            return _CmdResult()
        return self.argv_responses.get(args, _CmdResult())


# -- detect_tiktok --


def test_detect_tiktok_fast_path():
    adb = _FakeAdb()
    adb.shell_responses[f"pm path {TIKTOK_PACKAGES[0]}"] = f"package:/data/app/{TIKTOK_PACKAGES[0]}/base.apk\n"
    svc = LSPatchService(adb=adb, cache_dir=Path("/tmp/np-test-lspatch-1"))
    assert svc.detect_tiktok() == TIKTOK_PACKAGES[0]


def test_detect_tiktok_discovery_path():
    """A regional preload (com.tiktok.thai) is found via the pattern."""
    adb = _FakeAdb()
    # Empty path = not installed for every canonical name → fast path misses.
    for pkg in TIKTOK_PACKAGES:
        adb.shell_responses[f"pm path {pkg}"] = ""
    adb.shell_responses["pm list packages"] = (
        "package:com.android.settings\n"
        "package:com.tiktok.thai\n"
        "package:com.google.android.gms\n"
    )
    svc = LSPatchService(adb=adb, cache_dir=Path("/tmp/np-test-lspatch-2"))
    assert svc.detect_tiktok() == "com.tiktok.thai"


def test_detect_tiktok_returns_empty_when_none_installed():
    adb = _FakeAdb()
    for pkg in TIKTOK_PACKAGES:
        adb.shell_responses[f"pm path {pkg}"] = ""
    adb.shell_responses["pm list packages"] = (
        "package:com.android.settings\npackage:com.spotify.music\n"
    )
    svc = LSPatchService(adb=adb, cache_dir=Path("/tmp/np-test-lspatch-3"))
    assert svc.detect_tiktok() == ""


# -- probe_tools --


def test_probe_tools_flags_missing_adb(tmp_path: Path):
    """When adb is unavailable, probe should refuse — the rest of the
    pipeline can't function without it."""
    adb = _FakeAdb()
    adb.available = False
    # Provide valid paths for the host-side tools so they don't dominate
    # the error list; we want to confirm adb specifically is detected.
    jar = tmp_path / "lspatch.jar"
    jar.write_bytes(b"fake")
    apk = tmp_path / "receiver.apk"
    apk.write_bytes(b"fake")
    svc = LSPatchService(
        adb=adb, cache_dir=tmp_path / "cache",
        lspatch_jar=jar, receiver_apk=apk,
    )
    st = svc.probe_tools()
    assert not st.ok
    assert any("adb" in e.lower() for e in st.errors), st.errors


def test_probe_tools_finds_explicit_paths(tmp_path: Path):
    adb = _FakeAdb()
    jar = tmp_path / "lspatch.jar"
    jar.write_bytes(b"fake jar")
    apk = tmp_path / "receiver.apk"
    apk.write_bytes(b"fake apk")
    svc = LSPatchService(
        adb=adb,
        cache_dir=tmp_path / "cache",
        lspatch_jar=jar,
        receiver_apk=apk,
    )
    st = svc.probe_tools()
    # adb + java exist on the host; lspatch + receiver are explicit.
    assert st.lspatch == jar
    assert st.receiver_apk == apk
    # Java may or may not be 21+, can't assert ok without controlling that.


# -- installed_status --


def test_installed_status_returns_empty_when_no_tiktok():
    adb = _FakeAdb()
    for pkg in TIKTOK_PACKAGES:
        adb.shell_responses[f"pm path {pkg}"] = ""
    adb.shell_responses["pm list packages"] = "package:com.example\n"
    svc = LSPatchService(adb=adb, cache_dir=Path("/tmp/np-test-lspatch-4"))
    s = svc.installed_status()
    assert s.package == ""
    assert s.is_patched is False


def test_installed_status_detects_lspatch_fingerprint():
    adb = _FakeAdb()
    adb.shell_responses[f"pm path {TIKTOK_PACKAGES[0]}"] = (
        f"package:/data/app/{TIKTOK_PACKAGES[0]}/base.apk\n"
    )
    adb.shell_responses[f"dumpsys package {TIKTOK_PACKAGES[0]}"] = (
        "    versionName=45.0.3\n"
        "    signatures=PackageSignatures{abc version:2, "
        "signatures:[e0b8d3e5], past signatures:[]}\n"
    )
    svc = LSPatchService(adb=adb, cache_dir=Path("/tmp/np-test-lspatch-5"))
    s = svc.installed_status()
    assert s.package == TIKTOK_PACKAGES[0]
    assert s.version_name == "45.0.3"
    assert s.fingerprint == "e0b8d3e5"
    assert s.is_patched is True


def test_installed_status_detects_stock_signature():
    adb = _FakeAdb()
    adb.shell_responses[f"pm path {TIKTOK_PACKAGES[0]}"] = (
        f"package:/data/app/{TIKTOK_PACKAGES[0]}/base.apk\n"
    )
    adb.shell_responses[f"dumpsys package {TIKTOK_PACKAGES[0]}"] = (
        "    versionName=45.0.3\n"
        "    signatures=PackageSignatures{abc, signatures:[2606a464], past signatures:[]}\n"
    )
    svc = LSPatchService(adb=adb, cache_dir=Path("/tmp/np-test-lspatch-6"))
    s = svc.installed_status()
    assert s.fingerprint == "2606a464"
    assert s.is_patched is False


# -- _unwrap_lspatched --


def test_unwrap_lspatched_replaces_patched_apks(tmp_path: Path):
    """If an APK contains assets/lspatch/origin.apk, its bytes should be
    swapped with that inner APK so re-patching can start clean."""
    # Build an inner "real" APK (any zip works).
    real_apk = tmp_path / "real.zip"
    with zipfile.ZipFile(real_apk, "w") as zf:
        zf.writestr("classes.dex", b"REAL DEX BYTES")

    # Wrap it as a fake LSPatched APK.
    patched = tmp_path / "patched.apk"
    with zipfile.ZipFile(patched, "w") as zf:
        zf.writestr("classes.dex", b"WRAPPER DEX")
        zf.writestr("assets/lspatch/origin.apk", real_apk.read_bytes())
        zf.writestr("assets/lspatch/loader.dex", b"loader")

    result = LSPatchService._unwrap_lspatched([patched])
    assert result == [patched]
    # patched now contains the INNER zip's content.
    with zipfile.ZipFile(patched, "r") as zf:
        assert "classes.dex" in zf.namelist()
        assert zf.read("classes.dex") == b"REAL DEX BYTES"
        assert "assets/lspatch/origin.apk" not in zf.namelist()


def test_unwrap_lspatched_passthrough_unpatched_apks(tmp_path: Path):
    """APKs without an embedded origin should be returned untouched."""
    plain = tmp_path / "plain.apk"
    with zipfile.ZipFile(plain, "w") as zf:
        zf.writestr("classes.dex", b"PLAIN")

    snapshot = plain.read_bytes()
    result = LSPatchService._unwrap_lspatched([plain])
    assert result == [plain]
    assert plain.read_bytes() == snapshot
