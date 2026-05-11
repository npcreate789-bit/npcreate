from npcreate_studio.services.device_identity import DeviceIdentityService
from npcreate_studio.domain.licenses import DeviceType


def test_phone_identity_is_stable():
    svc = DeviceIdentityService(salt="test")
    meta = {"serial": "abc", "manufacturer": "NP", "model": "Phone", "android_id": "123"}
    a = svc.phone_identity(meta)
    b = svc.phone_identity(dict(reversed(list(meta.items()))))
    assert a.device_type == DeviceType.PHONE
    assert a.fingerprint_hash == b.fingerprint_hash
