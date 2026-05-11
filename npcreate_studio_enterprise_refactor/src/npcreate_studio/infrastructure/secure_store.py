from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from ..core.security import ensure_private_file

TOKENS_FILE = "tokens.enc"


class SecureStore:
    """Small encrypted local store for tokens/license secrets.

    Production note:
    - On Windows installer builds, protect `master.key` with DPAPI or replace this class
      with a keyring/Windows Credential Manager adapter.
    - This fallback keeps secrets encrypted at rest and permission-restricted for development.
    """

    def __init__(self, app_data_dir: Path) -> None:
        self.app_data_dir = app_data_dir
        self.key_path = app_data_dir / "master.key"
        self.key = self._load_or_create_key()
        self.fernet = Fernet(self.key)

    def _load_or_create_key(self) -> bytes:
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        if self.key_path.is_file():
            return base64.urlsafe_b64decode(self.key_path.read_text(encoding="ascii"))
        key = Fernet.generate_key()
        self.key_path.write_text(base64.urlsafe_b64encode(key).decode("ascii"), encoding="ascii")
        ensure_private_file(self.key_path)
        return key

    def encrypt(self, value: str) -> bytes:
        return self.fernet.encrypt(value.encode("utf-8"))

    def decrypt(self, value: bytes) -> str:
        try:
            return self.fernet.decrypt(value).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("stored secret cannot be decrypted") from exc

    @staticmethod
    def now() -> int:
        return int(time.time())

    # --- activation token persistence ------------------------------------
    # tokens stored as encrypted JSON in app_data_dir/tokens.enc.
    # JSON shape: {license_id, device_id, access_token, refresh_token,
    #              access_expires_at, refresh_expires_at, saved_at}

    @property
    def tokens_path(self) -> Path:
        return self.app_data_dir / TOKENS_FILE

    def save_tokens(self, payload: dict[str, Any]) -> None:
        """Encrypt + atomically write the activation/refresh token bundle."""
        encrypted = self.encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        tmp = self.tokens_path.with_suffix(".tmp")
        tmp.write_bytes(encrypted)
        ensure_private_file(tmp)
        tmp.replace(self.tokens_path)

    def get_tokens(self) -> dict[str, Any] | None:
        if not self.tokens_path.is_file():
            return None
        try:
            decoded = self.decrypt(self.tokens_path.read_bytes())
        except ValueError:
            return None
        try:
            return json.loads(decoded)
        except json.JSONDecodeError:
            return None

    def clear_tokens(self) -> None:
        self.tokens_path.unlink(missing_ok=True)
