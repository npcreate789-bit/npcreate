"""Phase C4 — Onboarding wizard state machine tests.

The Tk page itself depends on a display + the toast manager so we don't
test the UI directly. We DO unit-test the pure state transitions that
decide which step is current — typos here would silently send the user
to the wrong step on first run.
"""
from __future__ import annotations

from npcreate_studio.domain.devices import Device, DeviceConnection, DeviceState
from npcreate_studio.services.onboarding import (
    STATUS_CURRENT,
    STATUS_DONE,
    STATUS_UPCOMING,
    TOTAL_STEPS,
    OnboardingState,
    authorized_devices,
    best_device_to_recommend,
    current_step,
    is_complete,
    step_label,
    step_status,
)

# ---------- step_status: progression --------------------------------------


def test_status_step_1_current_when_fresh_state():
    statuses = step_status(OnboardingState())
    assert statuses[1] == STATUS_CURRENT
    for step in range(2, TOTAL_STEPS + 1):
        assert statuses[step] == STATUS_UPCOMING


def test_status_step_1_and_2_done_after_activation():
    statuses = step_status(OnboardingState(has_activation=True))
    assert statuses[1] == STATUS_DONE
    assert statuses[2] == STATUS_DONE
    assert statuses[3] == STATUS_CURRENT
    assert statuses[4] == STATUS_UPCOMING
    assert statuses[5] == STATUS_UPCOMING


def test_status_step_3_done_when_device_selected():
    statuses = step_status(OnboardingState(has_activation=True, selected_serial="ABC"))
    assert statuses[3] == STATUS_DONE
    assert statuses[4] == STATUS_CURRENT
    assert statuses[5] == STATUS_UPCOMING


def test_status_step_4_done_when_reverse_active():
    statuses = step_status(OnboardingState(
        has_activation=True, selected_serial="ABC", reverse_active=True,
    ))
    assert statuses[4] == STATUS_DONE
    assert statuses[5] == STATUS_CURRENT


def test_status_step_3_not_done_without_activation_even_if_serial_present():
    """Serial alone is not enough — user must activate first."""
    statuses = step_status(OnboardingState(selected_serial="ABC"))
    assert statuses[1] == STATUS_CURRENT
    assert statuses[3] != STATUS_DONE


# ---------- current_step -------------------------------------------------


def test_current_step_starts_at_one():
    assert current_step(OnboardingState()) == 1


def test_current_step_advances_after_activation():
    assert current_step(OnboardingState(has_activation=True)) == 3


def test_current_step_returns_5_when_fully_setup():
    state = OnboardingState(has_activation=True, selected_serial="ABC", reverse_active=True)
    assert current_step(state) == 5


# ---------- is_complete --------------------------------------------------


def test_is_complete_false_for_fresh_state():
    assert is_complete(OnboardingState()) is False


def test_is_complete_false_when_reverse_missing():
    state = OnboardingState(has_activation=True, selected_serial="ABC", reverse_active=False)
    assert is_complete(state) is False


def test_is_complete_true_when_all_four_done():
    state = OnboardingState(has_activation=True, selected_serial="ABC", reverse_active=True)
    assert is_complete(state) is True


# ---------- step_label ---------------------------------------------------


def test_step_labels_are_thai_strings():
    for step in range(1, TOTAL_STEPS + 1):
        label = step_label(step)
        assert label, f"step {step} should have a non-empty label"
    # The wizard's chips advertise specific concepts — make sure those don't
    # silently regress.
    assert "License" in step_label(1)
    assert "Activate" in step_label(2)
    assert "อุปกรณ์" in step_label(3)
    assert "Bridge" in step_label(4) or "adb reverse" in step_label(4)
    assert "ไลฟ์" in step_label(5)


def test_step_label_unknown_returns_question_mark():
    assert step_label(99) == "?"


# ---------- authorized_devices / best_device_to_recommend ----------------


def test_authorized_filters_to_state_device():
    devices = [
        Device(serial="A", state=DeviceState.DEVICE, connection=DeviceConnection.USB),
        Device(serial="B", state=DeviceState.UNAUTHORIZED),
        Device(serial="C", state=DeviceState.OFFLINE),
        Device(serial="D", state=DeviceState.DEVICE),
    ]
    auth = authorized_devices(devices)
    assert {d.serial for d in auth} == {"A", "D"}


def test_best_device_returns_first_authorized():
    devices = [
        Device(serial="B", state=DeviceState.UNAUTHORIZED),
        Device(serial="A", state=DeviceState.DEVICE),
        Device(serial="C", state=DeviceState.DEVICE),
    ]
    chosen = best_device_to_recommend(devices)
    assert chosen is not None
    assert chosen.serial == "A"


def test_best_device_returns_none_when_no_authorized():
    chosen = best_device_to_recommend([
        Device(serial="A", state=DeviceState.UNAUTHORIZED),
        Device(serial="B", state=DeviceState.OFFLINE),
    ])
    assert chosen is None


def test_best_device_returns_none_for_empty_list():
    assert best_device_to_recommend([]) is None


# ---------- end-to-end progression --------------------------------------


def test_state_progresses_linearly_as_user_completes_each_step():
    state = OnboardingState()
    progression: list[int] = []

    progression.append(current_step(state))
    state.license_key_input = "NP-XXX"
    progression.append(current_step(state))  # entering key alone does not advance
    state.has_activation = True
    progression.append(current_step(state))
    state.selected_serial = "ABC"
    progression.append(current_step(state))
    state.reverse_active = True
    progression.append(current_step(state))

    assert progression == [1, 1, 3, 4, 5]
