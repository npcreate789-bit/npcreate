from datetime import timedelta

import pytest

from npcreate_backend.security import create_token, hash_license_key, verify_token


def test_license_key_hash_is_case_insensitive_and_peppered():
    assert hash_license_key("np-abcd", "pepper1") == hash_license_key("NP-ABCD", "pepper1")
    assert hash_license_key("NP-ABCD", "pepper1") != hash_license_key("NP-ABCD", "pepper2")


def test_activation_token_roundtrip():
    token = create_token("secret-secret-secret-secret", "lic1", {"device_id": "dev1"}, timedelta(minutes=5))
    claims = verify_token("secret-secret-secret-secret", token)
    assert claims["sub"] == "lic1"
    assert claims["device_id"] == "dev1"


def test_activation_token_rejects_wrong_secret():
    token = create_token("secret-secret-secret-secret", "lic1", {}, timedelta(minutes=5))
    with pytest.raises(ValueError):
        verify_token("wrong-secret-secret-secret", token)
