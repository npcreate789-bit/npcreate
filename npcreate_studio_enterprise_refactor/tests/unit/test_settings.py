import pytest
from pydantic import ValidationError

from npcreate_studio.core.settings import Settings


def test_dashboard_host_must_be_local() -> None:
    with pytest.raises(ValidationError):
        Settings(dashboard_host="0.0.0.0")
