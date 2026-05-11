from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ..core.errors import SubprocessBlocked
from ..core.logging import redact
from ..core.security import safe_join

log = logging.getLogger(__name__)

DEFAULT_ALLOWED_NAMES = {
    "adb.exe", "adb", "fastboot.exe", "fastboot",
    "ffmpeg.exe", "ffmpeg", "ffprobe.exe", "ffprobe",
    "scrcpy.exe", "scrcpy",
    "mediamtx.exe", "mediamtx",
    "java.exe", "java",
}

SAFE_ENV_ALLOWLIST = {
    "PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "USERNAME", "USERPROFILE",
    "HOME", "LANG", "LC_ALL",
}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class CommandPolicy:
    allowed_names: frozenset[str] = frozenset(DEFAULT_ALLOWED_NAMES)
    allowed_roots: tuple[Path, ...] = ()
    default_timeout: float = 30.0
    max_output_chars: int = 80_000


class SubprocessRunner:
    """Centralized subprocess runner for production.

    Security defaults:
    - never uses shell=True
    - validates executable basename and optional root path
    - sanitizes environment
    - has timeout by default
    - truncates and redacts output before logging
    """

    def __init__(self, policy: CommandPolicy | None = None) -> None:
        self.policy = policy or CommandPolicy()

    def _validate_executable(self, executable: str | Path) -> Path | str:
        exe = Path(executable)
        name = exe.name or str(executable)
        if name not in self.policy.allowed_names:
            raise SubprocessBlocked(f"executable is not allowed: {name}")
        if exe.is_absolute() and self.policy.allowed_roots:
            resolved = exe.resolve()
            for root in self.policy.allowed_roots:
                try:
                    resolved.relative_to(root.resolve())
                    return resolved
                except ValueError:
                    continue
            raise SubprocessBlocked(f"executable outside allowed roots: {resolved}")
        return str(executable)

    def _clean_env(self, extra_env: Mapping[str, str] | None = None) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k in SAFE_ENV_ALLOWLIST}
        if extra_env:
            for k, v in extra_env.items():
                if k in SAFE_ENV_ALLOWLIST or k.startswith("NPCREATE_"):
                    env[k] = v
        return env

    def run(
        self,
        args: Sequence[str | Path],
        *,
        timeout: float | None = None,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
    ) -> CommandResult:
        if not args:
            raise ValueError("args must not be empty")
        exe = self._validate_executable(args[0])
        clean_args = [str(exe), *[str(a) for a in args[1:]]]
        if cwd is not None and self.policy.allowed_roots:
            # cwd must sit inside one of the allowed roots.
            ok = False
            for root in self.policy.allowed_roots:
                try:
                    safe_join(root, cwd.resolve())
                    ok = True
                    break
                except Exception:
                    pass
            if not ok:
                raise SubprocessBlocked(f"cwd outside allowed roots: {cwd}")

        log.info("subprocess start: %s", redact(" ".join(clean_args)))
        try:
            proc = subprocess.run(
                clean_args,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout or self.policy.default_timeout,
                check=False,
                shell=False,
                cwd=str(cwd) if cwd else None,
                env=self._clean_env(env),
            )
            stdout = proc.stdout[-self.policy.max_output_chars:]
            stderr = proc.stderr[-self.policy.max_output_chars:]
            result = CommandResult(proc.returncode, stdout, stderr)
            log.info("subprocess done code=%s stderr=%s", result.returncode, redact(stderr[:500]))
            return result
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            log.warning("subprocess timeout: %s", redact(" ".join(clean_args)))
            return CommandResult(124, stdout, stderr, timed_out=True)
