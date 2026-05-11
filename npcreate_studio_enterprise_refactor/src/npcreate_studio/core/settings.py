from __future__ import annotations

import os
import platform
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_app_data_dir() -> Path:
    if os.environ.get("NPCREATE_APP_DATA_DIR"):
        return Path(os.environ["NPCREATE_APP_DATA_DIR"]).expanduser()
    system = platform.system().lower()
    if system == "windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "NPCreate" / "Studio"
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "NPCreate" / "Studio"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "npcreate-studio"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NPCREATE_", env_file=".env", extra="ignore")

    env: str = Field(default="production")
    log_level: str = Field(default="INFO")
    dashboard_host: str = Field(default="127.0.0.1")
    dashboard_port: int = Field(default=8765, ge=1024, le=65535)
    enable_demo_routes: bool = Field(default=False)

    app_version: str = Field(default="2.4.0")
    update_channel: str = Field(default="stable")
    update_manifest_url: str | None = Field(default=None)
    license_server_url: str | None = Field(default=None)
    vendor_public_key_hex: str | None = Field(default=None)
    app_api_key: str | None = Field(default=None)

    tool_root: str = Field(default="vendor/windows")
    tools_manifest: str = Field(default="tools_manifest.json")
    app_data_dir: str | None = Field(default=None)

    activation_token_key: str = Field(default="activation_token")
    refresh_token_key: str = Field(default="activation_refresh_token")

    @field_validator("dashboard_host")
    @classmethod
    def dashboard_must_be_local(cls, value: str) -> str:
        allowed = {"127.0.0.1", "localhost", "::1"}
        if value not in allowed:
            raise ValueError("dashboard_host must stay localhost in production")
        return value

    @field_validator("update_channel")
    @classmethod
    def validate_channel(cls, value: str) -> str:
        allowed = {"stable", "beta", "dev"}
        if value not in allowed:
            raise ValueError(f"update_channel must be one of {sorted(allowed)}")
        return value

    @property
    def app_data_path(self) -> Path:
        p = Path(self.app_data_dir).expanduser() if self.app_data_dir else default_app_data_dir()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def tool_root_path(self) -> Path:
        return Path(self.tool_root).expanduser().resolve()

    @property
    def tools_manifest_path(self) -> Path:
        return Path(self.tools_manifest).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self.app_data_path / "npcreate_studio.sqlite3"

    @property
    def client_state_path(self) -> Path:
        return self.app_data_path / "client_state.json"
