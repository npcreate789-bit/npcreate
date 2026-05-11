"""Pure helpers for the Device Profile CRUD page.

Validation + formatting only — the Tk page owns widget plumbing. Pulling
these out keeps the rules unit-testable without a display.
"""
from __future__ import annotations

from collections.abc import Mapping

from ..domain.device_profiles import DeviceProfile, DeviceProfileLibrary, ProfileSource


def validate_profile_form(
    *,
    name: str,
    library: DeviceProfileLibrary,
    allow_replace: str = "",
) -> str | None:
    """Return a Thai error message, or ``None`` if the form is valid.

    ``allow_replace`` is the original profile name when editing an existing
    USER profile — we allow the same name to keep working without "duplicate"
    rejection. Builtin profiles cannot be replaced (UI hides the edit form
    for them, but we double-check).
    """
    trimmed = name.strip()
    if not trimmed:
        return "ใส่ชื่อ Profile ก่อน"
    if len(trimmed) > 80:
        return "ชื่อยาวเกินไป (สูงสุด 80 ตัวอักษร)"
    existing = library.get(trimmed)
    if existing is None:
        return None
    if existing.source == ProfileSource.BUILTIN and trimmed != allow_replace:
        return f"ชื่อ '{trimmed}' ใช้แล้วใน builtin (ห้าม override ทับชื่อเดิม)"
    if existing.source == ProfileSource.USER and trimmed != allow_replace:
        return f"ชื่อ '{trimmed}' มี user profile อยู่แล้ว"
    return None


def is_editable(profile: DeviceProfile) -> bool:
    """User-source profiles can be edited/deleted; builtins are read-only."""
    return profile.source == ProfileSource.USER


def profile_row_summary(profile: DeviceProfile) -> Mapping[str, str]:
    """Dict label → value for the per-row summary."""
    rotation_label = profile.rotation_filter or "—"
    return {
        "Source": "builtin (read-only)" if profile.source == ProfileSource.BUILTIN else "user",
        "Model": profile.model or "—",
        "Rotation": rotation_label,
        "SoC hint": profile.soc_hint or "—",
        "Notes": profile.notes or "—",
    }


def make_profile_from_form(
    *,
    name: str,
    model: str,
    rotation_filter: str,
    soc_hint: str,
    notes: str,
) -> DeviceProfile:
    """Build a fresh USER-source DeviceProfile from raw form values.

    All string fields are trimmed; empty ``model`` defaults to ``"generic"``
    so the on-disk JSON looks identical to legacy library entries.
    """
    name_t = name.strip()
    model_t = model.strip() or "generic"
    rotation_t = rotation_filter.strip()
    soc_t = soc_hint.strip()
    notes_t = notes.strip()
    return DeviceProfile(
        name=name_t,
        model=model_t,
        soc_hint=soc_t,
        rotation_filter=rotation_t,
        notes=notes_t,
        source=ProfileSource.USER,
    )


def library_counts(library: DeviceProfileLibrary) -> Mapping[str, int]:
    """Stat line for the page header."""
    total = len(library.profiles)
    user = sum(1 for p in library.profiles if p.source == ProfileSource.USER)
    builtin = total - user
    return {"total": total, "user": user, "builtin": builtin}
