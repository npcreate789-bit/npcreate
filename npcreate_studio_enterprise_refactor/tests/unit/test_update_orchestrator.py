"""Phase E1 — UpdateOrchestrator + version compare + atomic patch apply."""
from __future__ import annotations

import threading
import time
import zipfile
from pathlib import Path

import pytest

from npcreate_studio.core.errors import SecurityError
from npcreate_studio.services.update_client import UpdateManifestResponse
from npcreate_studio.services.update_orchestrator import (
    UpdateApplyError,
    UpdateOrchestrator,
    apply_source_patch,
    is_newer,
    parse_version,
)

# -- version compare ------------------------------------------------------


def test_parse_version_basic():
    assert parse_version("1.5.0") == (1, 5, 0)


def test_parse_version_strips_prerelease():
    assert parse_version("2.0.0-beta") == (2, 0, 0)
    assert parse_version("2.0.0+build123") == (2, 0, 0)


def test_parse_version_returns_empty_on_garbage():
    assert parse_version("not-a-version") == ()
    assert parse_version("1.x.0") == ()


def test_is_newer_basic():
    assert is_newer("1.5.1", "1.5.0") is True
    assert is_newer("1.5.0", "1.5.1") is False
    assert is_newer("1.5.0", "1.5.0") is False


def test_is_newer_handles_different_segment_counts():
    assert is_newer("2.0.0", "1.99.99") is True
    assert is_newer("1.5", "1.4.99") is True


def test_is_newer_false_when_either_side_malformed():
    assert is_newer("garbage", "1.0.0") is False
    assert is_newer("1.0.0", "garbage") is False


# -- apply_source_patch ---------------------------------------------------


def _make_zip(tmp_path: Path, *, files: dict[str, bytes], prefix: str = "") -> Path:
    zip_path = tmp_path / "patch.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for rel, content in files.items():
            name = f"{prefix}{rel}" if prefix else rel
            zf.writestr(name, content)
    return zip_path


def _make_src(parent: Path, name: str = "src", extra: dict[str, bytes] | None = None) -> Path:
    src = parent / name
    src.mkdir()
    (src / "main.py").write_bytes(b"# old main\n")
    for rel, content in (extra or {}).items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return src


def test_apply_source_patch_replaces_directory(tmp_path: Path):
    src = _make_src(tmp_path, extra={"core/settings.py": b"# old\n"})
    zip_path = _make_zip(tmp_path, files={
        "main.py": b"# new main\n",
        "core/settings.py": b"VERSION = '1.5.1'\n",
    })

    bak = apply_source_patch(zip_path, target_src_dir=src)
    assert src.exists()
    assert (src / "main.py").read_bytes() == b"# new main\n"
    assert (src / "core" / "settings.py").read_bytes() == b"VERSION = '1.5.1'\n"
    assert bak.is_dir()
    assert (bak / "main.py").read_bytes() == b"# old main\n"


def test_apply_source_patch_strips_top_level_prefix(tmp_path: Path):
    src = _make_src(tmp_path)
    zip_path = _make_zip(tmp_path, prefix="src/", files={"main.py": b"# new\n"})
    apply_source_patch(zip_path, target_src_dir=src)
    assert (src / "main.py").read_bytes() == b"# new\n"


def test_apply_source_patch_rejects_path_traversal(tmp_path: Path):
    src = _make_src(tmp_path)
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../../etc/passwd", b"oops")
    with pytest.raises(UpdateApplyError, match="unsafe path"):
        apply_source_patch(zip_path, target_src_dir=src)
    # Original src/ untouched.
    assert (src / "main.py").read_bytes() == b"# old main\n"
    # .new staging cleaned up.
    assert not (tmp_path / "src.new").exists()


def test_apply_source_patch_rejects_corrupt_zip(tmp_path: Path):
    src = _make_src(tmp_path)
    zip_path = tmp_path / "bad.zip"
    zip_path.write_bytes(b"not a zip file")
    with pytest.raises(UpdateApplyError, match="extract failed"):
        apply_source_patch(zip_path, target_src_dir=src)
    assert (src / "main.py").read_bytes() == b"# old main\n"


def test_apply_source_patch_rejects_missing_sentinel(tmp_path: Path):
    src = _make_src(tmp_path)
    zip_path = _make_zip(tmp_path, files={"other.py": b"# something\n"})
    with pytest.raises(UpdateApplyError, match="sentinel"):
        apply_source_patch(zip_path, target_src_dir=src, sentinel_files=("main.py",))
    # Original src/ untouched.
    assert (src / "main.py").read_bytes() == b"# old main\n"


def test_apply_source_patch_replaces_existing_bak(tmp_path: Path):
    src = _make_src(tmp_path)
    stale_bak = tmp_path / "src.bak"
    stale_bak.mkdir()
    (stale_bak / "stale.txt").write_text("from a prior failed attempt")
    zip_path = _make_zip(tmp_path, files={"main.py": b"# new\n"})

    new_bak = apply_source_patch(zip_path, target_src_dir=src)
    assert new_bak == stale_bak
    # The stale file is gone; bak now holds the OLD live src/.
    assert not (new_bak / "stale.txt").exists()
    assert (new_bak / "main.py").read_bytes() == b"# old main\n"


# -- UpdateOrchestrator ---------------------------------------------------


def _manifest(version: str = "1.5.1") -> UpdateManifestResponse:
    return UpdateManifestResponse(
        version=version,
        channel="stable",
        mandatory=False,
        download_url="https://example.com/p.zip",
        sha256="a" * 64,
        signature="00" * 64,
    )


class _StubClient:
    """Drop-in for UpdateClient. Pops manifests off a fixed queue; verify
    is a no-op unless ``verify_raises`` is set."""

    def __init__(self, manifests: list[UpdateManifestResponse | None]) -> None:
        self._manifests = list(manifests)
        self.calls = 0
        self.verify_calls = 0
        self.verify_raises = False
        self.last_token: str | None = None

    def check_latest(self, activation_token: str | None = None) -> UpdateManifestResponse | None:
        self.calls += 1
        self.last_token = activation_token
        if not self._manifests:
            return None
        return self._manifests.pop(0)

    def verify_manifest_signature(self, manifest: UpdateManifestResponse) -> None:
        self.verify_calls += 1
        if self.verify_raises:
            raise SecurityError("bad signature")


def test_check_now_returns_manifest_when_newer():
    client = _StubClient([_manifest("1.5.1")])
    orch = UpdateOrchestrator(client=client, current_version="1.5.0")
    m = orch.check_now()
    assert m is not None
    assert m.version == "1.5.1"
    assert client.verify_calls == 1


def test_check_now_returns_none_when_same_version():
    client = _StubClient([_manifest("1.5.0")])
    orch = UpdateOrchestrator(client=client, current_version="1.5.0")
    assert orch.check_now() is None
    # No signature work if version already current.
    assert client.verify_calls == 0


def test_check_now_returns_none_when_signature_invalid():
    client = _StubClient([_manifest("1.5.1")])
    client.verify_raises = True
    orch = UpdateOrchestrator(client=client, current_version="1.5.0")
    assert orch.check_now() is None


def test_check_now_returns_none_when_client_raises():
    class Boom:
        def check_latest(self, activation_token=None):
            raise RuntimeError("network down")

        def verify_manifest_signature(self, manifest):  # pragma: no cover
            raise AssertionError("should not be called")

    orch = UpdateOrchestrator(client=Boom(), current_version="1.5.0")
    assert orch.check_now() is None


def test_token_provider_is_passed_through():
    client = _StubClient([None])
    orch = UpdateOrchestrator(
        client=client,
        current_version="1.5.0",
        token_provider=lambda: "fake-jwt",
    )
    orch.check_now()
    assert client.last_token == "fake-jwt"


def test_polling_dedupes_repeated_version():
    client = _StubClient([_manifest("1.5.1"), _manifest("1.5.1"), _manifest("1.5.1")])
    seen: list[str] = []
    callback_fired = threading.Event()

    def cb(m: UpdateManifestResponse) -> None:
        seen.append(m.version)
        callback_fired.set()

    orch = UpdateOrchestrator(
        client=client,
        current_version="1.5.0",
        poll_interval_s=0.05,
        startup_delay_s=0.0,
    )
    orch.start_polling(cb)
    assert callback_fired.wait(timeout=2.0)
    # Allow another two poll intervals so the dedup logic gets exercised.
    time.sleep(0.2)
    orch.stop_polling()
    assert seen == ["1.5.1"]
    assert client.calls >= 2


def test_polling_calls_back_on_each_new_version():
    client = _StubClient([_manifest("1.5.1"), _manifest("1.5.2")])
    seen: list[str] = []
    done = threading.Event()

    def cb(m: UpdateManifestResponse) -> None:
        seen.append(m.version)
        if len(seen) >= 2:
            done.set()

    orch = UpdateOrchestrator(
        client=client,
        current_version="1.5.0",
        poll_interval_s=0.05,
        startup_delay_s=0.0,
    )
    orch.start_polling(cb)
    assert done.wait(timeout=2.0)
    orch.stop_polling()
    assert seen == ["1.5.1", "1.5.2"]


def test_polling_swallows_callback_exceptions_and_keeps_running():
    client = _StubClient([_manifest("1.5.1"), _manifest("1.5.2")])
    seen: list[str] = []
    second_seen = threading.Event()

    def cb(m: UpdateManifestResponse) -> None:
        seen.append(m.version)
        if m.version == "1.5.1":
            raise RuntimeError("UI not ready yet")
        second_seen.set()

    orch = UpdateOrchestrator(
        client=client,
        current_version="1.5.0",
        poll_interval_s=0.05,
        startup_delay_s=0.0,
    )
    orch.start_polling(cb)
    assert second_seen.wait(timeout=2.0)
    orch.stop_polling()
    assert seen == ["1.5.1", "1.5.2"]


def test_polling_stops_cleanly():
    client = _StubClient([_manifest("1.5.1")])
    orch = UpdateOrchestrator(
        client=client,
        current_version="1.5.0",
        poll_interval_s=10.0,
        startup_delay_s=0.0,
    )
    orch.start_polling(lambda m: None)
    assert orch.is_polling()
    orch.stop_polling()
    assert not orch.is_polling()


def test_polling_double_start_is_idempotent():
    client = _StubClient([_manifest("1.5.1")])
    orch = UpdateOrchestrator(
        client=client,
        current_version="1.5.0",
        poll_interval_s=10.0,
        startup_delay_s=0.0,
    )
    orch.start_polling(lambda m: None)
    first_thread = orch._thread
    orch.start_polling(lambda m: None)
    assert orch._thread is first_thread
    orch.stop_polling()
