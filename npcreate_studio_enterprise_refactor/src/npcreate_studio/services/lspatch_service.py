"""LSPatch pipeline — fuse the Android receiver into the user's TikTok APK.

This is the **non-root** injection path. The open-source LSPatch tool
(https://github.com/JingMatrix/LSPatch) embeds our Xposed module
(``npcreate_studio_android`` debug APK) directly into TikTok's APK.
The patched APK boots a tiny Xposed framework loader on its own — no
root, no Magisk, no system-wide LSPosed required.

End-to-end flow (4 phases, GUI exposes each as a step):

  1. ``probe_tools()``  — verify java 21+, lspatch.jar, receiver APK, adb
  2. ``pull_tiktok()``  — adb pull every base.apk + split_*.apk
  3. ``patch()``        — run lspatch.jar to embed our module into each
  4. ``install()``      — uninstall stock TikTok, install-multiple patched

After the install:
  5. User logs into TikTok again (signature changed → fresh sandbox).
  6. The receiver's ``CameraHook`` fires the moment TikTok's main process
     starts. Going Live then replaces the camera feed with whatever
     MP4 sits at ``/sdcard/vcam_final.mp4`` (sentinel file on/off
     toggle: ``/data/local/tmp/vcam_enabled``).

Hard requirements on the host machine:
  - **JDK 21+** (LSPatch is built against Java 21 class files)
  - **lspatch.jar** vendored locally (under ``.tools/lspatch/`` by
    default) or downloaded via ``scripts/fetch_lspatch.sh``
  - **adb** on PATH or in vendor manifest

Anti-patterns this module guards against:

  * Never patch + install in one step without an explicit user
    confirmation — the install destroys the original TikTok session.
  * Never assume splits aren't required; always ``install-multiple``
    with all patched splits, otherwise PM rejects with
    ``INSTALL_FAILED_MISSING_SPLIT``.
  * Re-patching an already-patched APK fails because of zip-entry
    overlap; we unwrap LSPatched APKs back to their embedded
    ``assets/lspatch/origin.apk`` before re-running the patch.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .adb_service import AdbService

log = logging.getLogger(__name__)

# Canonical TikTok variants we recognise. Edit this list to support
# additional regional builds; the pattern-matcher below catches
# preload SKUs and beta variants we haven't hardcoded.
TIKTOK_PACKAGES: tuple[str, ...] = (
    "com.ss.android.ugc.trill",      # International (en, th, …)
    "com.zhiliaoapp.musically",       # Musically variant
    "com.ss.android.ugc.aweme",       # Douyin (China)
)

_TIKTOK_PKG_PATTERN = re.compile(
    r"^(?:com\.ss\.android\.ugc\.(?:trill|aweme|musically|tiktok)"
    r"|com\.zhiliaoapp\.musically"
    r"|com\.tiktok\.[\w.]+)"
    r"(?:\.[\w]+)*$"
)


# ── result types ─────────────────────────────────────────────────────────


@dataclass
class ToolStatus:
    """``probe_tools()`` output — the GUI uses ``ok`` to gate the patch button
    and ``errors`` to show per-tool messages."""

    java: Path | None = None
    java_version: str = ""
    lspatch: Path | None = None
    receiver_apk: Path | None = None
    adb: str = "adb"
    ok: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class PullResult:
    ok: bool
    package: str = ""
    version_name: str = ""
    apks: list[Path] = field(default_factory=list)
    elapsed_s: float = 0.0
    error: str = ""


@dataclass
class PatchResult:
    ok: bool
    output_dir: Path
    patched_apks: list[Path] = field(default_factory=list)
    elapsed_s: float = 0.0
    error: str = ""
    log_tail: str = ""


@dataclass
class InstallResult:
    ok: bool
    elapsed_s: float = 0.0
    error: str = ""
    fingerprint: str = ""
    rollback_attempted: bool = False
    rollback_ok: bool = False
    rollback_error: str = ""


# ── service ──────────────────────────────────────────────────────────────


class LSPatchService:
    """Pull → patch → install. Each step is independently callable so the
    GUI can drive them as 4 separate buttons + show progress between.

    Defaults to looking up tools under ``<repo>/.tools/lspatch/`` and
    ``<repo>/../npcreate_studio_android/app/build/outputs/apk/debug/`` so
    a fresh checkout works without extra setup if the user has already
    built the receiver APK + run ``scripts/fetch_lspatch.sh``.
    """

    JAVA_MIN_MAJOR = 21

    def __init__(
        self,
        adb: AdbService,
        *,
        cache_dir: Path,
        lspatch_jar: Path | None = None,
        receiver_apk: Path | None = None,
        java_path: Path | None = None,
    ) -> None:
        self.adb = adb
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.pulled_dir = self.cache_dir / "pulled"
        self.patched_dir = self.cache_dir / "patched"
        self._lspatch_jar = lspatch_jar
        self._receiver_apk = receiver_apk
        self._java_path = java_path

    # ── tool discovery ──────────────────────────────────────────────

    def probe_tools(self) -> ToolStatus:
        st = ToolStatus(adb="adb")

        # Java 21+
        java = self._resolve_java()
        if java is None:
            st.errors.append(
                "JDK 21+ not found. Install via 'brew install openjdk@25' "
                "or set java_path explicitly.",
            )
        else:
            st.java = java
            try:
                r = subprocess.run(
                    [str(java), "-version"],
                    capture_output=True, text=True, timeout=5, check=False,
                )
                # `java -version` writes to stderr by convention.
                first_line = (r.stderr or r.stdout or "").splitlines()
                vstr = first_line[0] if first_line else ""
                st.java_version = vstr.strip()
                m = re.search(r'"(\d+)\.', vstr) or re.search(r'"(\d+)"', vstr)
                major = int(m.group(1)) if m else 0
                if major < self.JAVA_MIN_MAJOR:
                    st.errors.append(
                        f"Java {major} too old — LSPatch needs JDK {self.JAVA_MIN_MAJOR}+",
                    )
            except (subprocess.TimeoutExpired, OSError) as exc:
                st.errors.append(f"java probe failed: {exc}")

        # lspatch.jar
        jar = self._resolve_lspatch_jar()
        if jar is None:
            st.errors.append(
                "lspatch.jar not found. Run scripts/fetch_lspatch.sh, or "
                "place it under .tools/lspatch/lspatch.jar",
            )
        else:
            st.lspatch = jar

        # Receiver APK (the Xposed module that gets embedded)
        apk = self._resolve_receiver_apk()
        if apk is None:
            st.errors.append(
                "Receiver APK not found. Build it via "
                "'./gradlew :app:assembleDebug' in npcreate_studio_android/",
            )
        else:
            st.receiver_apk = apk

        # adb
        if not self.adb.is_available():
            st.errors.append("adb not available — install adb or set vendor manifest")

        st.ok = not st.errors
        return st

    # ── detect TikTok ───────────────────────────────────────────────

    def detect_tiktok(self, serial: str | None = None) -> str:
        """Return the installed TikTok variant package name, or empty.

        Fast path: exact match against TIKTOK_PACKAGES. Discovery path:
        scan ``pm list packages`` for anything that matches the pattern
        — covers OEM-preload + beta + regional variants we don't ship.
        """
        for pkg in TIKTOK_PACKAGES:
            if self._pkg_installed(pkg, serial):
                return pkg

        listing = self._adb_shell("pm list packages", serial)
        for line in listing.splitlines():
            line = line.strip()
            if not line.startswith("package:"):
                continue
            pkg = line[len("package:"):].strip()
            if _TIKTOK_PKG_PATTERN.match(pkg):
                log.info("detect_tiktok: discovered non-canonical TikTok %r", pkg)
                return pkg
        return ""

    def _pkg_installed(self, pkg: str, serial: str | None) -> bool:
        out = self._adb_shell(f"pm path {pkg}", serial)
        return bool(out and out.startswith("package:"))

    # ── pull ────────────────────────────────────────────────────────

    def pull_tiktok(
        self,
        package: str = "",
        serial: str | None = None,
    ) -> PullResult:
        """``adb pull`` every APK in TikTok's split bundle into the cache.

        TikTok ships as base.apk + 30-50 split APKs (locale, ABI, feature
        modules). All must be patched + reinstalled together or PM
        rejects with INSTALL_FAILED_MISSING_SPLIT.
        """
        if not package:
            package = self.detect_tiktok(serial)
        if not package:
            return PullResult(False, error="no TikTok variant installed")

        if self.pulled_dir.exists():
            shutil.rmtree(self.pulled_dir)
        self.pulled_dir.mkdir(parents=True, exist_ok=True)

        out = self._adb_shell(f"pm path {package}", serial)
        paths = [
            line[len("package:"):].strip()
            for line in out.splitlines()
            if line.startswith("package:")
        ]
        if not paths:
            return PullResult(False, package=package, error="pm path returned nothing")

        version_out = self._adb_shell(
            f"dumpsys package {package} | grep -m1 versionName", serial,
        )
        m = re.search(r"versionName=(\S+)", version_out)
        version_name = m.group(1) if m else "?"

        t0 = time.monotonic()
        pulled: list[Path] = []
        for p in paths:
            fname = p.rsplit("/", 1)[-1]
            dst = self.pulled_dir / fname
            result = self.adb.exec_argv("pull", p, str(dst), serial=serial, timeout=180.0)
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip().splitlines()[-2:]
                return PullResult(
                    False,
                    package=package,
                    version_name=version_name,
                    elapsed_s=time.monotonic() - t0,
                    error="\n".join(err),
                )
            pulled.append(dst)

        unwrapped = self._unwrap_lspatched(pulled)
        return PullResult(
            ok=True,
            package=package,
            version_name=version_name,
            apks=unwrapped,
            elapsed_s=time.monotonic() - t0,
        )

    @staticmethod
    def _unwrap_lspatched(apks: Iterable[Path]) -> list[Path]:
        """Re-patching a patched APK trips ``zipfile``'s overlap check. If
        the pulled APK already carries ``assets/lspatch/origin.apk``,
        replace it with the embedded original via ``unzip -p`` (the
        Info-ZIP CLI ignores the overlap heuristic)."""
        unzip = shutil.which("unzip")
        out: list[Path] = []
        for apk in apks:
            try:
                with zipfile.ZipFile(apk, "r") as zf:
                    if "assets/lspatch/origin.apk" not in zf.namelist():
                        out.append(apk)
                        continue
            except zipfile.BadZipFile:
                out.append(apk)
                continue

            tmp = apk.with_suffix(apk.suffix + ".origin")
            extracted = False
            try:
                with zipfile.ZipFile(apk, "r") as zf, \
                     zf.open("assets/lspatch/origin.apk") as src, \
                     tmp.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted = True
            except zipfile.BadZipFile as e:
                if "Overlapped" not in str(e) or unzip is None:
                    log.warning("unwrap %s failed: %s", apk.name, e)
                else:
                    with tmp.open("wb") as dst:
                        proc = subprocess.run(
                            [unzip, "-p", str(apk), "assets/lspatch/origin.apk"],
                            stdout=dst, stderr=subprocess.PIPE,
                            timeout=120, check=False,
                        )
                    if proc.returncode == 0 and tmp.stat().st_size > 0:
                        extracted = True
                        log.info("unwrap %s: used unzip -p fallback", apk.name)
                    else:
                        log.warning(
                            "unwrap %s: unzip -p failed rc=%d", apk.name, proc.returncode,
                        )

            if extracted:
                tmp.replace(apk)
                log.info("unwrapped lspatched APK: %s", apk.name)
            elif tmp.exists():
                tmp.unlink()
            out.append(apk)
        return out

    # ── patch ───────────────────────────────────────────────────────

    def patch(self, apks: list[Path], *, sigbypass_level: int = 2) -> PatchResult:
        """Invoke ``lspatch.jar`` over every input APK.

        ``sigbypass_level=2`` hooks both PackageManager AND openat() so
        TikTok's runtime self-signature checks see the original
        signature, not LSPatch's debug key.
        """
        st = self.probe_tools()
        if not st.ok:
            return PatchResult(False, self.patched_dir, error="; ".join(st.errors))
        assert st.java and st.lspatch and st.receiver_apk

        if self.patched_dir.exists():
            shutil.rmtree(self.patched_dir)
        self.patched_dir.mkdir(parents=True, exist_ok=True)

        cmd: list[str] = [
            str(st.java),
            "-jar", str(st.lspatch),
            *[str(a) for a in apks],
            "-m", str(st.receiver_apk),
            "-l", str(sigbypass_level),
            "-f",
            "-o", str(self.patched_dir),
        ]
        log.info("LSPatch: %d input APKs → %s", len(apks), self.patched_dir)

        # Force C locale: Java's apkzlib uses MsDosDateTimeUtils which
        # accepts years 1980-2107 only. On Thai macOS the JVM defaults to
        # BuddhistCalendar (year 2569) → patch crashes with VerifyException.
        import os
        env = {**os.environ, "LANG": "C", "LC_ALL": "C", "TZ": "UTC"}

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600, check=False, env=env,
            )
        except subprocess.TimeoutExpired:
            return PatchResult(
                False, self.patched_dir,
                elapsed_s=time.monotonic() - t0,
                error="lspatch timed out (>10 min)",
            )

        elapsed = time.monotonic() - t0
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-15:]
            return PatchResult(
                False, self.patched_dir,
                elapsed_s=elapsed,
                error=f"lspatch exited rc={proc.returncode}",
                log_tail="\n".join(tail),
            )

        outputs = sorted(self.patched_dir.glob("*-lspatched.apk"))
        if not outputs:
            tail = (proc.stdout or "").strip().splitlines()[-15:]
            return PatchResult(
                False, self.patched_dir,
                elapsed_s=elapsed,
                error="lspatch produced no output APKs",
                log_tail="\n".join(tail),
            )

        return PatchResult(
            ok=True,
            output_dir=self.patched_dir,
            patched_apks=outputs,
            elapsed_s=elapsed,
        )

    # ── install ─────────────────────────────────────────────────────

    def install(
        self,
        package: str,
        patched_apks: list[Path],
        *,
        serial: str | None = None,
        uninstall_first: bool = True,
        original_apks: list[Path] | None = None,
    ) -> InstallResult:
        """Uninstall stock TikTok → install-multiple the patched bundle.

        DESTRUCTIVE: kills the user's TikTok login session. Confirm with
        the user first. On failure post-uninstall, attempts to roll back
        by reinstalling the original APKs (callers should pass them via
        ``original_apks`` so the rollback can find them).
        """
        if not patched_apks:
            return InstallResult(False, error="no patched APKs to install")

        t0 = time.monotonic()
        if uninstall_first:
            self.adb.exec_argv("uninstall", package, serial=serial, timeout=30.0)

        argv = ["install-multiple", "-r", *[str(p) for p in patched_apks]]
        try:
            r = self.adb.exec_argv(*argv, serial=serial, timeout=600.0)
        except subprocess.TimeoutExpired:
            return self._rollback(
                package, original_apks, serial=serial, t0=t0,
                error="install-multiple timed out",
            )
        elapsed = time.monotonic() - t0
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip().splitlines()[-3:]
            return self._rollback(
                package, original_apks, serial=serial, t0=t0,
                error="install-multiple failed: " + "\n".join(err),
            )

        # Fetch the installed-signature fingerprint so the GUI can confirm
        # the patched APK won (vs an old install lingering).
        fingerprint = self._read_fingerprint(package, serial)
        return InstallResult(ok=True, elapsed_s=elapsed, fingerprint=fingerprint)

    def _rollback(
        self,
        package: str,
        original_apks: list[Path] | None,
        *,
        serial: str | None,
        t0: float,
        error: str,
    ) -> InstallResult:
        result = InstallResult(
            ok=False,
            elapsed_s=time.monotonic() - t0,
            error=error,
            rollback_attempted=bool(original_apks),
        )
        if not original_apks:
            return result
        try:
            self.adb.exec_argv("uninstall", package, serial=serial, timeout=30.0)
            argv = ["install-multiple", *[str(p) for p in original_apks]]
            r = self.adb.exec_argv(*argv, serial=serial, timeout=600.0)
            if r.returncode == 0:
                result.rollback_ok = True
                log.info("rolled back to original APKs for %s", package)
            else:
                result.rollback_error = (
                    r.stderr or r.stdout or ""
                ).strip().splitlines()[-3:][0]
        except Exception as exc:
            result.rollback_error = str(exc)
        return result

    def _read_fingerprint(self, package: str, serial: str | None) -> str:
        out = self._adb_shell(f"dumpsys package {package} | grep -m1 signatures=", serial)
        m = re.search(r"signatures:\[(\w+)\]", out)
        return m.group(1) if m else ""

    # ── status ──────────────────────────────────────────────────────

    @dataclass
    class InstalledStatus:
        package: str = ""
        version_name: str = ""
        fingerprint: str = ""
        is_patched: bool = False

    LSPATCH_FINGERPRINT = "e0b8d3e5"

    def installed_status(self, serial: str | None = None) -> LSPatchService.InstalledStatus:
        status = self.InstalledStatus()
        pkg = self.detect_tiktok(serial)
        if not pkg:
            return status
        status.package = pkg

        dump = self._adb_shell(f"dumpsys package {pkg}", serial)
        m = re.search(r"versionName=(\S+)", dump)
        if m:
            status.version_name = m.group(1)
        m = re.search(r"signatures:\[(\w+)\]", dump)
        if m:
            status.fingerprint = m.group(1)
            status.is_patched = status.fingerprint == self.LSPATCH_FINGERPRINT
        return status

    # ── helpers ─────────────────────────────────────────────────────

    def _adb_shell(self, cmd: str, serial: str | None) -> str:
        result = self.adb.exec_argv(
            "shell", cmd, serial=serial, timeout=15.0,
        )
        return result.stdout if result.returncode == 0 else ""

    def _resolve_java(self) -> Path | None:
        if self._java_path and self._java_path.is_file():
            return self._java_path
        # Try common locations
        candidates = [
            "/opt/homebrew/opt/openjdk@25/bin/java",
            "/opt/homebrew/opt/openjdk@21/bin/java",
            "/opt/homebrew/opt/openjdk/bin/java",
        ]
        for p in candidates:
            if Path(p).is_file():
                return Path(p)
        which = shutil.which("java")
        return Path(which) if which else None

    def _resolve_lspatch_jar(self) -> Path | None:
        if self._lspatch_jar and self._lspatch_jar.is_file():
            return self._lspatch_jar
        # Look in repo's .tools/lspatch/
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        for path in (
            repo_root / ".tools" / "lspatch" / "lspatch.jar",
            repo_root.parent / ".tools" / "lspatch" / "lspatch.jar",
        ):
            if path.is_file():
                return path
        return None

    def _resolve_receiver_apk(self) -> Path | None:
        if self._receiver_apk and self._receiver_apk.is_file():
            return self._receiver_apk
        # Look in sibling repo's debug build output
        refactor_root = Path(__file__).resolve().parent.parent.parent.parent
        android_root = refactor_root.parent / "npcreate_studio_android"
        candidates = (
            android_root / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk",
            refactor_root / ".tools" / "receiver" / "app-debug.apk",
        )
        for path in candidates:
            if path.is_file():
                return path
        return None


__all__ = [
    "TIKTOK_PACKAGES",
    "InstallResult",
    "LSPatchService",
    "PatchResult",
    "PullResult",
    "ToolStatus",
]
