"""Phase B2 — DeviceProfileLibrary + repository tests.

Covers in-memory library behaviour (get/find/add/remove/merge), JSON
roundtrip for the user-writable side, and auto_detect against fake adb
``getprop`` output.
"""
from __future__ import annotations

import json
from pathlib import Path

from npcreate_studio.domain.device_profiles import (
    GENERIC_PROFILE,
    DeviceProfile,
    DeviceProfileLibrary,
    ProfileSource,
)
from npcreate_studio.services.device_profile_repository import (
    auto_detect,
    load_builtin,
    load_combined,
    load_user,
    save_user,
)

# -- DeviceProfileLibrary (domain) ----------------------------------------


def test_library_always_includes_generic_fallback():
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="X", model="X-model"),
    ])
    assert lib.get(GENERIC_PROFILE.name) is not None


def test_library_names_preserves_insertion_order():
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="A"),
        DeviceProfile(name="B"),
    ])
    names = lib.names()
    # Generic gets appended by __post_init__ if not present
    assert names[:2] == ["A", "B"]
    assert GENERIC_PROFILE.name in names


def test_library_find_by_model_is_case_insensitive():
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="Redmi 13C", model="23100RN82L"),
    ])
    found = lib.find_by_model("23100rn82l")
    assert found is not None
    assert found.name == "Redmi 13C"


def test_library_find_by_model_returns_none_for_unknown():
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="A", model="model-a"),
    ])
    assert lib.find_by_model("nonexistent") is None
    assert lib.find_by_model("") is None


def test_library_add_replaces_by_name():
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="A", model="old-model", rotation_filter="none"),
    ])
    lib.add(DeviceProfile(name="A", model="new-model", rotation_filter="transpose=1", source=ProfileSource.USER))
    found = lib.get("A")
    assert found is not None
    assert found.model == "new-model"
    assert found.rotation_filter == "transpose=1"
    assert found.source == ProfileSource.USER


def test_library_add_appends_new_profile():
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="A"),
    ])
    lib.add(DeviceProfile(name="B", source=ProfileSource.USER))
    assert "B" in lib.names()


def test_library_remove_only_removes_user_profiles():
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="builtin", source=ProfileSource.BUILTIN),
        DeviceProfile(name="mine", source=ProfileSource.USER),
    ])
    assert lib.remove("mine") is True
    assert lib.remove("builtin") is False
    assert lib.get("builtin") is not None
    assert lib.get("mine") is None


def test_library_user_profiles_filter():
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="builtin1", source=ProfileSource.BUILTIN),
        DeviceProfile(name="user1", source=ProfileSource.USER),
        DeviceProfile(name="user2", source=ProfileSource.USER),
    ])
    users = lib.user_profiles()
    assert {p.name for p in users} == {"user1", "user2"}


def test_library_merge_user_overrides_builtin_by_name():
    builtin = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="A", model="builtin-A", rotation_filter="none", source=ProfileSource.BUILTIN),
        DeviceProfile(name="B", model="builtin-B", source=ProfileSource.BUILTIN),
    ])
    user = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="A", model="user-A", rotation_filter="transpose=1", source=ProfileSource.USER),
        DeviceProfile(name="C", model="user-C", source=ProfileSource.USER),
    ])
    merged = DeviceProfileLibrary.merge(builtin, user)
    assert merged.get("A").model == "user-A"
    assert merged.get("A").source == ProfileSource.USER
    assert merged.get("B").source == ProfileSource.BUILTIN
    assert merged.get("C").source == ProfileSource.USER


# -- repository: builtin load --------------------------------------------


def test_load_builtin_returns_shipped_starter_profiles():
    lib = load_builtin()
    names = lib.names()
    # We ship Redmi 13C (legacy-confirmed), Generic, and Test as starters.
    assert "Redmi 13C" in names
    assert GENERIC_PROFILE.name in names
    # All builtin entries are tagged accordingly.
    for name in ("Redmi 13C", "Generic / unknown"):
        profile = lib.get(name)
        assert profile is not None
        assert profile.source == ProfileSource.BUILTIN


# -- repository: user JSON roundtrip -------------------------------------


def test_load_user_returns_empty_when_file_missing(tmp_path: Path):
    lib = load_user(tmp_path / "missing.json")
    # Library always at least has the GENERIC fallback inserted by __post_init__.
    assert lib.names() == [GENERIC_PROFILE.name]


def test_save_user_only_persists_user_source_entries(tmp_path: Path):
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="builtin", source=ProfileSource.BUILTIN),
        DeviceProfile(name="mine", model="my-phone", rotation_filter="transpose=2", source=ProfileSource.USER),
    ])
    path = tmp_path / "device_profiles.json"
    save_user(lib, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    names = [p["name"] for p in raw["profiles"]]
    assert names == ["mine"]
    assert raw["profiles"][0]["rotation_filter"] == "transpose=2"


def test_save_user_atomic_write_replaces_existing(tmp_path: Path):
    path = tmp_path / "device_profiles.json"
    path.write_text('{"profiles": []}', encoding="utf-8")
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="A", source=ProfileSource.USER),
    ])
    save_user(lib, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert [p["name"] for p in raw["profiles"]] == ["A"]
    # .tmp must not linger after the atomic replace.
    assert not path.with_suffix(".tmp").exists()


def test_load_user_handles_corrupt_json(tmp_path: Path):
    path = tmp_path / "device_profiles.json"
    path.write_text("not-json", encoding="utf-8")
    lib = load_user(path)
    # Survives gracefully — empty library (plus Generic fallback).
    assert lib.names() == [GENERIC_PROFILE.name]


def test_load_combined_merges_builtin_and_user(tmp_path: Path):
    path = tmp_path / "device_profiles.json"
    path.write_text(json.dumps({
        "profiles": [
            {"name": "Redmi 13C", "model": "user-override-model", "rotation_filter": "none"},
            {"name": "My Custom Phone", "model": "user-phone", "rotation_filter": "transpose=1"},
        ]
    }), encoding="utf-8")
    lib = load_combined(user_path=path)
    redmi = lib.get("Redmi 13C")
    assert redmi is not None
    assert redmi.model == "user-override-model"
    assert redmi.source == ProfileSource.USER
    custom = lib.get("My Custom Phone")
    assert custom is not None
    assert custom.source == ProfileSource.USER


# -- repository: auto_detect ---------------------------------------------


def test_auto_detect_exact_model_match():
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="Redmi 13C", model="23100RN82L", rotation_filter="transpose=2,vflip"),
    ])
    profile = auto_detect(lib, props={"ro.product.model": "23100RN82L", "ro.product.cpu.abi": "arm64-v8a"})
    assert profile.name == "Redmi 13C"
    assert profile.rotation_filter == "transpose=2,vflip"


def test_auto_detect_falls_back_to_generic_when_unknown_model():
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="Known", model="known-model"),
    ])
    profile = auto_detect(lib, props={"ro.product.model": "UnknownPhoneXYZ"})
    assert profile.name == GENERIC_PROFILE.name


def test_auto_detect_returns_generic_when_props_empty():
    lib = DeviceProfileLibrary(profiles=[
        DeviceProfile(name="Known", model="known-model"),
    ])
    profile = auto_detect(lib, props={})
    assert profile.name == GENERIC_PROFILE.name
