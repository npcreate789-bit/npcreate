"""subprocess.Popen wrapper for long-running streaming children (FFmpeg, scrcpy).

`SubprocessRunner` (one-shot) uses `subprocess.run`, which buffers all output —
not suitable for streaming H.264 to a TCP socket. This helper keeps the same
security guarantees (executable allowlist, env sanitization) but exposes the
live `Popen` so callers can read stdout in chunks.

Use only inside services that need to consume streaming I/O; if you just need
to run a one-shot command, prefer `SubprocessRunner`.
"""
from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import SubprocessBlocked
from ..core.logging import redact
from .subprocess_runner import DEFAULT_ALLOWED_NAMES, SAFE_ENV_ALLOWLIST

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StreamingPolicy:
    allowed_names: frozenset[str] = frozenset(DEFAULT_ALLOWED_NAMES)
    allowed_roots: tuple[Path, ...] = ()
    extra_env_allowlist: frozenset[str] = frozenset()


class StreamingSubprocess:
    """Spawn a child process whose stdout is consumed live."""

    def __init__(self, policy: StreamingPolicy | None = None) -> None:
        self.policy = policy or StreamingPolicy()

    def _validate_executable(self, executable: str | Path) -> str:
        exe = Path(executable)
        name = exe.name or str(executable)
        if name not in self.policy.allowed_names:
            raise SubprocessBlocked(f"executable is not allowed: {name}")
        if exe.is_absolute() and self.policy.allowed_roots:
            resolved = exe.resolve()
            for root in self.policy.allowed_roots:
                try:
                    resolved.relative_to(root.resolve())
                    return str(resolved)
                except ValueError:
                    continue
            raise SubprocessBlocked(f"executable outside allowed roots: {resolved}")
        return str(executable)

    def _clean_env(self, extra_env: Mapping[str, str] | None = None) -> dict[str, str]:
        allowed = SAFE_ENV_ALLOWLIST | self.policy.extra_env_allowlist
        env = {k: v for k, v in os.environ.items() if k in allowed}
        if extra_env:
            for k, v in extra_env.items():
                if k in allowed or k.startswith("NPCREATE_"):
                    env[k] = v
        return env

    def start(
        self,
        args: Sequence[str | Path],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        capture_output: bool = True,
        detached: bool = False,
    ) -> subprocess.Popen:
        """Spawn the child. The two extra knobs cover GUI children like scrcpy:

        - ``capture_output=False`` — route stdout/stderr/stdin to DEVNULL so
          we don't fill OS pipe buffers with output we never read (the SDL
          window draws its own UI).
        - ``detached=True`` — pass ``start_new_session=True`` so a Ctrl-C
          in the parent terminal doesn't propagate down into the child.
        """
        if not args:
            raise ValueError("args must not be empty")
        exe = self._validate_executable(args[0])
        cmd = [exe, *[str(a) for a in args[1:]]]
        log.info("streaming subprocess start: %s", redact(" ".join(cmd)))
        if capture_output:
            io_kwargs: dict[str, object] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
            }
        else:
            io_kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "stdin": subprocess.DEVNULL,
            }
        return subprocess.Popen(  # noqa: S603 — validated above
            cmd,
            bufsize=0,
            shell=False,
            cwd=str(cwd) if cwd else None,
            env=self._clean_env(env),
            start_new_session=detached,
            **io_kwargs,  # type: ignore[arg-type]
        )
