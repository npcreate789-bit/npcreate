"""Per-device profile: a named bundle of streaming quirks (mainly the FFmpeg
rotation filter) plus metadata so we can auto-detect from ``ro.product.model``.

Ported from legacy ``vcam-pc/src/config.py::DeviceProfile`` + ``ProfileLibrary``.
The legacy file stored profiles as plain JSON in the project root; we keep
the same shape but split builtin (ship-with-app) from user (writable) sources.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProfileSource(str, Enum):
    BUILTIN = "builtin"
    USER = "user"


@dataclass(frozen=True)
class DeviceProfile:
    name: str
    model: str = "generic"
    soc_hint: str = ""
    rotation_filter: str = ""  # "" means none; FFmpeg expression like "transpose=2,vflip"
    notes: str = ""
    source: ProfileSource = ProfileSource.BUILTIN


GENERIC_PROFILE = DeviceProfile(
    name="Generic / unknown",
    model="generic",
    rotation_filter="",
    notes="ใช้ก่อนถ้ายังไม่รู้รุ่น แล้วค่อยปรับ rotation_filter ถ้าภาพหมุน",
    source=ProfileSource.BUILTIN,
)


@dataclass
class DeviceProfileLibrary:
    """Ordered collection of profiles. ``add`` keeps user entries after
    builtins so iteration order is stable, and overrides-by-name promote
    user variants over builtins of the same name."""

    profiles: list[DeviceProfile] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Always guarantee the Generic fallback exists; tests + cold-start
        # depend on `library.get("Generic / unknown")` returning a profile.
        if not any(p.name == GENERIC_PROFILE.name for p in self.profiles):
            self.profiles.append(GENERIC_PROFILE)

    def names(self) -> list[str]:
        return [p.name for p in self.profiles]

    def get(self, name: str) -> DeviceProfile | None:
        for p in self.profiles:
            if p.name == name:
                return p
        return None

    def find_by_model(self, model: str) -> DeviceProfile | None:
        """Match `ro.product.model` (e.g. ``23100RN82L``) against the library.
        Comparison is case-insensitive trimmed."""
        target = model.strip().lower()
        if not target:
            return None
        for p in self.profiles:
            if p.model and p.model.strip().lower() == target:
                return p
        return None

    def add(self, profile: DeviceProfile) -> None:
        """Append or replace by name. Keeps builtin ordering stable."""
        for i, existing in enumerate(self.profiles):
            if existing.name == profile.name:
                self.profiles[i] = profile
                return
        self.profiles.append(profile)

    def remove(self, name: str) -> bool:
        for i, p in enumerate(self.profiles):
            if p.name == name and p.source == ProfileSource.USER:
                del self.profiles[i]
                return True
        return False

    def user_profiles(self) -> list[DeviceProfile]:
        return [p for p in self.profiles if p.source == ProfileSource.USER]

    @classmethod
    def merge(cls, builtin: DeviceProfileLibrary, user: DeviceProfileLibrary) -> DeviceProfileLibrary:
        """Combine two libraries — user entries override builtin by name."""
        out_profiles: list[DeviceProfile] = list(builtin.profiles)
        for up in user.profiles:
            replaced = False
            for i, bp in enumerate(out_profiles):
                if bp.name == up.name:
                    out_profiles[i] = up
                    replaced = True
                    break
            if not replaced:
                out_profiles.append(up)
        return cls(profiles=out_profiles)
