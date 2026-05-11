"""Background update poller + atomic source-patch apply + relaunch.

Sits on top of ``UpdateClient`` (HTTP fetch + signature verify) and
``UpdaterService`` (byte-level verify + extract) — both already exist in
this package — and adds the three pieces the legacy ``auto_update.py`` had
that the refactor was missing:

1. A background poller that wakes every ``poll_interval_s`` and notifies a
   callback when the manifest's version moves forward. Dedup is by version
   string so a stuck CDN doesn't re-fire the banner every poll.
2. ``apply_source_patch`` — atomic ``src/`` swap with ``src.bak`` rollback,
   modeled on the legacy directory-rename trick. Safe on any modern FS.
3. ``relaunch`` — spawns a fresh app process via ``subprocess.Popen`` and
   exits the current one. Used right after a successful apply.

Everything here is **best-effort**: network failures, bad manifests, and
extract failures all log + return ``None`` rather than crash the host app.
The customer's runtime is never blocked by the updater.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NoReturn, Protocol

from ..core.errors import SecurityError
from .update_client import UpdateManifestResponse

log = logging.getLogger(__name__)


class _UpdateClientLike(Protocol):
    """Structural subset of ``UpdateClient`` the orchestrator actually uses.

    Lets tests inject a stub without subclassing the concrete httpx-backed
    client, and lets the production code accept the real one unchanged.
    """

    def check_latest(self, activation_token: str | None = None) -> UpdateManifestResponse | None: ...
    def verify_manifest_signature(self, manifest: UpdateManifestResponse) -> None: ...


# ── version compare ─────────────────────────────────────────────────────


def parse_version(v: str) -> tuple[int, ...]:
    """Parse ``"1.5.0"`` → ``(1, 5, 0)``. Strips pre-release / build tags.

    Returns the empty tuple on parse failure — callers use that to refuse
    auto-update from a manifest with a malformed version string.
    """
    head = v.split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for chunk in head.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            return ()
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    a = parse_version(candidate)
    b = parse_version(current)
    if not a or not b:
        return False
    return a > b


# ── atomic source-patch apply ───────────────────────────────────────────


class UpdateApplyError(Exception):
    """Raised by ``apply_source_patch`` when the patch can't be applied
    safely. The caller should treat this as a no-op — the live install is
    guaranteed to be in its pre-call state."""


def _zip_common_prefix(members: list[str]) -> str:
    if not members:
        return ""
    first = members[0]
    slash = first.find("/")
    if slash < 0:
        return ""
    prefix = first[: slash + 1]
    if any(not m.startswith(prefix) for m in members):
        return ""
    if prefix.startswith("__MACOSX"):
        return ""
    return prefix


def apply_source_patch(
    patch_zip: Path,
    *,
    target_src_dir: Path,
    sentinel_files: Iterable[str] = ("main.py",),
) -> Path:
    """Atomically replace ``target_src_dir`` with the contents of ``patch_zip``.

    Strategy:

    1. Extract into a sibling ``<name>.new`` directory.
    2. Verify at least one sentinel file exists (refuses to apply a patch
       that's missing the entry-point — would brick the install).
    3. Rename ``target_src_dir`` → ``<name>.bak``.
    4. Rename ``<name>.new`` → ``target_src_dir``.

    Returns the path to the ``.bak`` directory so the caller can delete it
    after the next launch confirms the new build boots. On any failure
    between steps 3 and 4 we attempt to restore from ``.bak``; if even
    that fails we log loudly and re-raise (manual intervention needed).
    """
    target_src_dir = target_src_dir.resolve()
    parent = target_src_dir.parent
    new = parent / f"{target_src_dir.name}.new"
    bak = parent / f"{target_src_dir.name}.bak"

    if new.exists():
        shutil.rmtree(new)
    new.mkdir(parents=True)

    try:
        with zipfile.ZipFile(patch_zip, "r") as zf:
            members = zf.namelist()
            prefix = _zip_common_prefix(members)
            for name in members:
                if name.endswith("/"):
                    continue
                rel = name[len(prefix):] if prefix else name
                rel_path = Path(rel)
                if rel_path.is_absolute() or ".." in rel_path.parts:
                    raise UpdateApplyError(f"unsafe path in patch: {name}")
                target = new / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as zsrc, open(target, "wb") as zdst:
                    shutil.copyfileobj(zsrc, zdst)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(new, ignore_errors=True)
        raise UpdateApplyError(f"patch extract failed: {exc}") from exc
    except UpdateApplyError:
        shutil.rmtree(new, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(new, ignore_errors=True)
        raise UpdateApplyError(f"patch extract failed: {exc}") from exc

    sentinels = list(sentinel_files)
    if sentinels and not any((new / f).is_file() for f in sentinels):
        shutil.rmtree(new, ignore_errors=True)
        raise UpdateApplyError(
            f"patch missing sentinel files {sentinels} — refusing to apply"
        )

    if bak.exists():
        shutil.rmtree(bak)
    try:
        os.rename(target_src_dir, bak)
    except OSError as exc:
        shutil.rmtree(new, ignore_errors=True)
        raise UpdateApplyError(
            f"could not move {target_src_dir.name} → {bak.name}: {exc}"
        ) from exc

    try:
        os.rename(new, target_src_dir)
    except OSError as exc:
        try:
            os.rename(bak, target_src_dir)
        except OSError:
            log.exception(
                "CRITICAL: could not restore %s from %s — manual intervention required",
                target_src_dir, bak,
            )
        raise UpdateApplyError(
            f"could not promote {new.name} → {target_src_dir.name}: {exc}"
        ) from exc

    log.info("update applied: %s (rollback at %s)", target_src_dir, bak)
    return bak


def relaunch(argv: list[str] | None = None, *, cwd: Path | None = None) -> NoReturn:
    """Spawn a fresh app process and exit. Caller should not return after
    this. Uses ``Popen`` (not ``execv``) so the new process gets a clean
    PID — some macOS Tk widgets get sticky if the executable is swapped
    mid-mainloop."""
    args = argv or [sys.executable, "-m", "npcreate_studio"]
    try:
        subprocess.Popen(args, cwd=str(cwd) if cwd else None)
    except OSError as exc:
        log.exception("relaunch spawn failed: %s", exc)
    os._exit(0)


# ── background poller ───────────────────────────────────────────────────


class UpdateOrchestrator:
    """Background poller around ``UpdateClient.check_latest()``.

    ``check_now()`` is the synchronous "user clicked Check" path.
    ``start_polling()`` spins up a daemon thread that calls back on each
    NEW version — dedup is by version string so a stalled manifest doesn't
    re-spam the banner every poll. Both paths verify the Ed25519 signature
    on the manifest before handing it off.
    """

    def __init__(
        self,
        *,
        client: _UpdateClientLike,
        current_version: str,
        token_provider: Callable[[], str | None] | None = None,
        poll_interval_s: float = 6 * 3600,
        startup_delay_s: float = 30.0,
    ) -> None:
        self._client = client
        self._current_version = current_version
        self._token_provider = token_provider or (lambda: None)
        self._poll_interval_s = max(0.0, float(poll_interval_s))
        self._startup_delay_s = max(0.0, float(startup_delay_s))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_seen_version: str | None = None
        self._on_update: Callable[[UpdateManifestResponse], None] | None = None

    def check_now(self) -> UpdateManifestResponse | None:
        """Synchronous "is there a newer build?" check. Returns the manifest
        if (a) the server gave one, (b) it's strictly newer than our current
        version, and (c) the Ed25519 signature verifies. Returns ``None`` on
        anything else — including transport failures."""
        try:
            manifest = self._client.check_latest(activation_token=self._token_provider())
        except Exception:
            log.exception("update check failed")
            return None
        if manifest is None:
            return None
        if not is_newer(manifest.version, self._current_version):
            return None
        try:
            self._client.verify_manifest_signature(manifest)
        except SecurityError:
            log.warning("update manifest signature invalid — ignoring %s", manifest.version)
            return None
        return manifest

    def start_polling(
        self,
        on_update: Callable[[UpdateManifestResponse], None],
    ) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._on_update = on_update
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name="np-update-poll", daemon=True,
        )
        self._thread.start()

    def stop_polling(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None

    def is_polling(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _poll_loop(self) -> None:
        if self._startup_delay_s > 0 and self._stop.wait(self._startup_delay_s):
            return
        while not self._stop.is_set():
            manifest = self.check_now()
            if manifest is not None and manifest.version != self._last_seen_version:
                self._last_seen_version = manifest.version
                cb = self._on_update
                if cb is not None:
                    try:
                        cb(manifest)
                    except Exception:
                        log.exception("on_update callback raised")
            if self._stop.wait(self._poll_interval_s):
                return


__all__ = [
    "UpdateApplyError",
    "UpdateOrchestrator",
    "apply_source_patch",
    "is_newer",
    "parse_version",
    "relaunch",
]
