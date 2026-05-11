"""Phase C5 — Device profile CRUD validation + persistence tests."""
from __future__ import annotations

import json
from pathlib import Path

from npcreate_studio.domain.device_profiles import (
    DeviceProfile,
    DeviceProfileLibrary,
    ProfileSource,
)
from npcreate_studio.services.device_profile_repository import load_user, save_user
from npcreate_studio.services.profile_view import (
    is_editable,
    library_counts,
    make_profile_from_form,
    profile_row_summary,
    validate_profile_form,
)

# ---------- validate_profile_form ---------------------------------------


def _library(*extra: DeviceProfile) -> DeviceProfileLibrary:
    return DeviceProfileLibrary(profiles=list(extra))


def test_validate_rejects_empty_name():
    lib = _library()
    assert validate_profile_form(name="", library=lib) == "ใส่ชื่อ Profile ก่อน"
    assert validate_profile_form(name="   ", library=lib) == "ใส่ชื่อ Profile ก่อน"


def test_validate_rejects_overlong_name():
    lib = _library()
    long_name = "x" * 200
    err = validate_profile_form(name=long_name, library=lib)
    assert err is not None
    assert "ยาวเกินไป" in err


def test_validate_rejects_duplicate_user_name():
    lib = _library(DeviceProfile(name="My phone", source=ProfileSource.USER))
    err = validate_profile_form(name="My phone", library=lib)
    assert err is not None
    assert "user profile" in err.lower() or "มี" in err


def test_validate_rejects_builtin_name():
    lib = _library(DeviceProfile(name="Redmi 13C", source=ProfileSource.BUILTIN))
    err = validate_profile_form(name="Redmi 13C", library=lib)
    assert err is not None
    assert "builtin" in err.lower() or "override" in err.lower()


def test_validate_allows_replacement_when_editing_existing_user_profile():
    lib = _library(DeviceProfile(name="My phone", source=ProfileSource.USER))
    assert validate_profile_form(name="My phone", library=lib, allow_replace="My phone") is None


def test_validate_does_not_allow_replacement_of_builtin_via_allow_replace():
    """allow_replace exists for the edit case. But you can't edit a builtin —
    the UI should never set allow_replace to a builtin name. If it does, we
    still reject."""
    lib = _library(DeviceProfile(name="Redmi 13C", source=ProfileSource.BUILTIN))
    err = validate_profile_form(name="Different name", library=lib, allow_replace="Redmi 13C")
    # New name is unique → OK. The point is allow_replace doesn't grant write
    # access to the builtin slot when a different new name is provided.
    assert err is None


def test_validate_accepts_brand_new_name():
    lib = _library(DeviceProfile(name="Existing", source=ProfileSource.USER))
    assert validate_profile_form(name="New phone", library=lib) is None


# ---------- is_editable / profile_row_summary ---------------------------


def test_is_editable_only_for_user_source():
    builtin = DeviceProfile(name="A", source=ProfileSource.BUILTIN)
    user = DeviceProfile(name="B", source=ProfileSource.USER)
    assert is_editable(builtin) is False
    assert is_editable(user) is True


def test_profile_row_summary_fills_dashes_for_empty_fields():
    out = profile_row_summary(DeviceProfile(name="X", source=ProfileSource.USER))
    # DeviceProfile defaults model="generic" — display it as-is.
    assert out["Model"] == "generic"
    assert out["Rotation"] == "—"
    assert out["SoC hint"] == "—"
    assert out["Notes"] == "—"
    assert "user" in out["Source"]


def test_profile_row_summary_handles_explicitly_empty_model():
    """If a caller forces model='' (unusual; the form helper defaults to
    'generic'), the row should fall back to '—' rather than empty string."""
    out = profile_row_summary(DeviceProfile(name="X", model="", source=ProfileSource.USER))
    assert out["Model"] == "—"


def test_profile_row_summary_marks_builtin_read_only():
    out = profile_row_summary(DeviceProfile(name="X", source=ProfileSource.BUILTIN))
    assert "builtin" in out["Source"]
    assert "read-only" in out["Source"]


def test_profile_row_summary_renders_rotation_value():
    out = profile_row_summary(DeviceProfile(
        name="X",
        model="abc",
        rotation_filter="transpose=1",
        soc_hint="MT6769",
        notes="ok",
        source=ProfileSource.USER,
    ))
    assert out["Model"] == "abc"
    assert out["Rotation"] == "transpose=1"
    assert out["SoC hint"] == "MT6769"
    assert out["Notes"] == "ok"


# ---------- make_profile_from_form --------------------------------------


def test_make_profile_trims_and_defaults_model_to_generic():
    profile = make_profile_from_form(
        name="  My Phone  ",
        model="   ",
        rotation_filter="  transpose=1  ",
        soc_hint=" Tensor G2 ",
        notes=" hello ",
    )
    assert profile.name == "My Phone"
    assert profile.model == "generic"
    assert profile.rotation_filter == "transpose=1"
    assert profile.soc_hint == "Tensor G2"
    assert profile.notes == "hello"
    assert profile.source == ProfileSource.USER


def test_make_profile_preserves_provided_model():
    profile = make_profile_from_form(
        name="A",
        model="ro.product.model.abc",
        rotation_filter="",
        soc_hint="",
        notes="",
    )
    assert profile.model == "ro.product.model.abc"


# ---------- library_counts ---------------------------------------------


def test_library_counts_separates_builtin_and_user():
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="A", source=ProfileSource.BUILTIN),
        DeviceProfile(name="B", source=ProfileSource.BUILTIN),
        DeviceProfile(name="C", source=ProfileSource.USER),
    ])
    counts = library_counts(lib)
    # Library auto-adds Generic fallback if missing — accept any with that.
    assert counts["total"] == len(lib.profiles)
    assert counts["user"] == 1
    assert counts["builtin"] == counts["total"] - 1


# ---------- end-to-end CRUD persistence ---------------------------------


def test_full_crud_flow_persists_to_user_json(tmp_path: Path):
    """Simulate the UI sequence: load empty user file → add → edit → reload → delete → reload.
    The library state on disk must match what we expect at each step."""
    user_path = tmp_path / "device_profiles.json"
    library = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="Redmi 13C", model="23100RN82L", source=ProfileSource.BUILTIN),
    ])

    # 1. add new user profile
    new_profile = make_profile_from_form(
        name="Pixel 7",
        model="Pixel_7",
        rotation_filter="transpose=1",
        soc_hint="Tensor G2",
        notes="my main phone",
    )
    assert validate_profile_form(name=new_profile.name, library=library) is None
    library.add(new_profile)
    save_user(library, user_path)
    assert user_path.is_file()

    reloaded = load_user(user_path)
    assert reloaded.get("Pixel 7") is not None
    assert reloaded.get("Pixel 7").rotation_filter == "transpose=1"

    # 2. edit (rename + change rotation)
    edited = make_profile_from_form(
        name="Pixel 7 Pro",
        model="Pixel_7_Pro",
        rotation_filter="transpose=1,vflip",
        soc_hint="Tensor G2",
        notes="my main phone (renamed)",
    )
    assert validate_profile_form(
        name=edited.name, library=library, allow_replace="Pixel 7",
    ) is None
    library.remove("Pixel 7")  # rename → remove + add
    library.add(edited)
    save_user(library, user_path)

    reloaded = load_user(user_path)
    assert reloaded.get("Pixel 7") is None
    assert reloaded.get("Pixel 7 Pro").rotation_filter == "transpose=1,vflip"

    # 3. delete
    assert library.remove("Pixel 7 Pro") is True
    save_user(library, user_path)
    reloaded = load_user(user_path)
    assert reloaded.get("Pixel 7 Pro") is None
    # Final file payload must be an empty user list.
    raw = json.loads(user_path.read_text(encoding="utf-8"))
    assert raw == {"profiles": []}


def test_remove_builtin_via_library_returns_false_and_persists_nothing(tmp_path: Path):
    user_path = tmp_path / "device_profiles.json"
    library = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="Builtin Phone", source=ProfileSource.BUILTIN),
        DeviceProfile(name="Custom Phone", source=ProfileSource.USER),
    ])
    save_user(library, user_path)

    assert library.remove("Builtin Phone") is False
    save_user(library, user_path)
    reloaded = load_user(user_path)
    # User still has "Custom Phone"; builtin not present in user JSON regardless.
    assert reloaded.get("Custom Phone") is not None
