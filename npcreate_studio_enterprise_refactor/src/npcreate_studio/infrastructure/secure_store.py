from __future__ import annotations

import base64
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ..core.security import ensure_private_file


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
