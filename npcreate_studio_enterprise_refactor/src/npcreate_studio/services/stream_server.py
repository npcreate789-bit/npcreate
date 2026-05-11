"""1-client TCP server that pumps a subprocess's stdout to the connected peer.

Lifecycle (ported from legacy ``vcam-pc/src/tcp_server.py``):

  bind → listen → accept ONE client → spawn child → pump stdout → on disconnect,
  kill child → accept next

Design notes:
- FFmpeg only runs while there's a client listening — saves CPU when the phone
  receiver app is not connected.
- H.264 Annex-B start codes are passed through raw; the receiver feeds them
  straight into MediaCodec. ``frames_sent`` is an approximation derived from
  counting start codes.
- Server runs in a background daemon thread so the UI stays responsive; ``stop``
  closes the listener, kills the child, and joins.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..domain.streams import StreamerStats, StreamStatus
from ..infrastructure.streaming_subprocess import StreamingSubprocess

log = logging.getLogger(__name__)

DEFAULT_CHUNK = 64 * 1024
ANNEX_B_START = b"\x00\x00\x00\x01"


@dataclass
class StreamServerConfig:
    host: str = "127.0.0.1"
    port: int = 8888
    chunk_size: int = DEFAULT_CHUNK
    accept_timeout_s: float = 0.5
    socket_timeout_s: float = 1.0


CmdFactory = Callable[[], list[str]]
StateCallback = Callable[[StreamerStats], None]


class StreamServer:
    """Accept a single TCP client, spawn a streaming subprocess on connect,
    forward stdout to the client until either side disconnects, then loop."""

    def __init__(
        self,
        config: StreamServerConfig,
        *,
        cmd_factory: CmdFactory,
        subprocess: StreamingSubprocess,
        cwd: Path | None = None,
        on_state: StateCallback | None = None,
    ) -> None:
        self.config = config
        self._cmd_factory = cmd_factory
        self._subprocess = subprocess
        self._cwd = cwd
        self._on_state = on_state or (lambda _s: None)
        self.stats = StreamerStats()
        self._thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._server_sock: socket.socket | None = None
        self._client_sock: socket.socket | None = None
        self._connected_at: float | None = None

    # -- public API ---------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("server already running")
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._serve_forever, daemon=True, name="np-stream-server")
        self._thread.start()

    def stop(self, *, join_timeout_s: float = 3.0) -> None:
        self._stop_evt.set()
        try:
            if self._client_sock is not None:
                self._client_sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            if self._server_sock is not None:
                self._server_sock.close()
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=join_timeout_s)
        self._set_status(StreamStatus.IDLE, client_addr="")

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # -- internals ---------------------------------------------------------

    def _set_status(self, status: StreamStatus, **fields: object) -> None:
        self.stats.status = status
        for k, v in fields.items():
            setattr(self.stats, k, v)
        if self._connected_at is not None:
            self.stats.uptime_s = time.monotonic() - self._connected_at
        try:
            self._on_state(self.stats)
        except Exception:
            log.exception("on_state callback failed")

    def _serve_forever(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((self.config.host, self.config.port))
        except OSError as exc:
            log.error("bind %s:%d failed: %s", self.config.host, self.config.port, exc)
            self._set_status(StreamStatus.ERROR, last_error=f"bind failed: {exc}")
            return
        srv.listen(1)
        srv.settimeout(self.config.accept_timeout_s)
        self._server_sock = srv
        self._set_status(StreamStatus.LISTENING)
        log.info("stream server listening on %s:%d", self.config.host, self.config.port)

        while not self._stop_evt.is_set():
            try:
                client, addr = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            self._client_sock = client
            self._connected_at = time.monotonic()
            self.stats.bytes_sent = 0
            self.stats.frames_sent = 0
            self._set_status(StreamStatus.CLIENT_CONNECTED, client_addr=f"{addr[0]}:{addr[1]}")
            try:
                self._pump(client)
            except Exception as exc:
                log.exception("pump error")
                self._set_status(StreamStatus.ERROR, last_error=str(exc)[:200])
            finally:
                try:
                    client.close()
                except OSError:
                    pass
                self._client_sock = None
                self._connected_at = None
                self._set_status(StreamStatus.LISTENING, client_addr="")

        try:
            srv.close()
        except OSError:
            pass

    def _pump(self, client: socket.socket) -> None:
        client.settimeout(self.config.socket_timeout_s)
        cmd = self._cmd_factory()
        proc = self._subprocess.start(cmd, cwd=self._cwd)
        self.stats.pid = proc.pid
        self._set_status(StreamStatus.STREAMING)
        try:
            assert proc.stdout is not None
            while not self._stop_evt.is_set():
                if proc.poll() is not None:
                    log.info("child exited rc=%s", proc.returncode)
                    break
                buf = proc.stdout.read(self.config.chunk_size)
                if not buf:
                    log.info("child stdout EOF")
                    break
                try:
                    client.sendall(buf)
                except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                    log.info("client gone: %s", exc)
                    break
                self.stats.bytes_sent += len(buf)
                self.stats.frames_sent += buf.count(ANNEX_B_START)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        pass
            self.stats.pid = None
