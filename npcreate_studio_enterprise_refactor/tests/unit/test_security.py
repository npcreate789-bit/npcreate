import zipfile
from pathlib import Path

import pytest

from npcreate_studio.core.errors import SecurityError
from npcreate_studio.core.security import is_safe_archive_member, safe_extract_zip, safe_join


def test_safe_join_blocks_escape(tmp_path: Path) -> None:
    with pytest.raises(SecurityError):
        safe_join(tmp_path, "..", "evil.txt")


def test_archive_member_validation() -> None:
    assert is_safe_archive_member("src/app.py")
    assert not is_safe_archive_member("../evil.py")
    assert not is_safe_archive_member("/tmp/evil.py")
    assert not is_safe_archive_member("C:/Windows/evil.exe")


def test_safe_extract_blocks_traversal(tmp_path: Path) -> None:
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../evil.txt", "bad")
    with pytest.raises(SecurityError):
        safe_extract_zip(z, tmp_path / "out")
