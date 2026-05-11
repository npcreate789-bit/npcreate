"""Load / save / merge DeviceProfileLibrary from JSON files.

Two sources are supported:

- **builtin** — ships inside the package at ``data/device_profiles.json``.
  Read-only at runtime. Provides starter profiles for common phones the
  legacy team already validated (Redmi 13C/14C, Poco C75, …).
- **user** — writable JSON under the client's app-data dir, e.g.
  ``<app_data>/device_profiles.json``. Users add their own profiles via
  the UI; entries override builtins by name when merged.

Auto-detection helper maps ``adb get_props`` output (``ro.product.model``)
to the best library match, with the Generic profile as a guaranteed
fallback.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path

from ..domain.device_profiles import (
    GENERIC_PROFILE,
    DeviceProfile,
    DeviceProfileLibrary,
    ProfileSource,
)

log = logging.getLogger(__name__)

BUILTIN_RESOURCE = "device_profiles.json"


def _load_from_path(path: Path, *, source: ProfileSource) -> DeviceProfileLibrary:
    if not path.is_file():
        return DeviceProfileLibrary(profiles=[])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.exception("failed to read profile library at %s — returning empty", path)
        return DeviceProfileLibrary(profiles=[])
    return _from_dict(raw, source=source)


def _from_dict(raw: Mapping[str, object], *, source: ProfileSource) -> DeviceProfileLibrary:
    profiles_data = raw.get("profiles") if isinstance(raw, Mapping) else None
    if not isinstance(profiles_data, list):
        return DeviceProfileLibrary(profiles=[])
    profiles: list[DeviceProfile] = []
    for item in profiles_data:
        if not isinstance(item, Mapping):
            continue
        profiles.append(DeviceProfile(
            name=str(item.get("name") or "?"),
            model=str(item.get("model") or "generic"),
            soc_hint=str(item.get("soc_hint") or ""),
            rotation_filter=str(item.get("rotation_filter") or ""),
            notes=str(item.get("notes") or ""),
            source=source,
        ))
    return DeviceProfileLibrary(profiles=profiles)


def load_builtin() -> DeviceProfileLibrary:
    """Load the ship-with-app library from the package's data resource."""
    try:
        data_files = files("npcreate_studio").joinpath("data", BUILTIN_RESOURCE)
        with data_files.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, OSError, ModuleNotFoundError, json.JSONDecodeError):
        log.warning("builtin device_profiles.json missing or invalid — falling back to Generic only")
        return DeviceProfileLibrary(profiles=[GENERIC_PROFILE])
    return _from_dict(raw, source=ProfileSource.BUILTIN)


def load_user(user_path: Path) -> DeviceProfileLibrary:
    """Load user-edited profiles, or empty library if file doesn't exist."""
    return _load_from_path(user_path, source=ProfileSource.USER)


def save_user(library: DeviceProfileLibrary, user_path: Path) -> None:
    """Persist only USER-source profiles back to disk (atomic via .tmp)."""
    payload = {
        "profiles": [
            {
                "name": p.name,
                "model": p.model,
                "soc_hint": p.soc_hint,
                "rotation_filter": p.rotation_filter,
                "notes": p.notes,
            }
            for p in library.user_profiles()
        ]
    }
    user_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = user_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(user_path)


def load_combined(*, user_path: Path) -> DeviceProfileLibrary:
    """Convenience: load builtin + user, merge, return."""
    return DeviceProfileLibrary.merge(load_builtin(), load_user(user_path))


def auto_detect(library: DeviceProfileLibrary, *, props: Mapping[str, str]) -> DeviceProfile:
    """Pick the best profile for a phone given its ``getprop`` output.

    Match priority:
    1. exact ``ro.product.model`` → library entry (case-insensitive)
    2. otherwise: GENERIC_PROFILE so the caller always gets *something*.
    """
    model = str(props.get("ro.product.model") or "").strip()
    if model:
        matched = library.find_by_model(model)
        if matched is not None:
            return matched
    return library.get(GENERIC_PROFILE.name) or GENERIC_PROFILE
