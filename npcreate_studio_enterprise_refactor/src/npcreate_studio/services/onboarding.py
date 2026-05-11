"""Pure logic for the first-run onboarding wizard.

The wizard has five steps:

  1. License — user pastes a license key
  2. Activate — call backend, persist tokens
  3. Pick device — choose a connected Android (authorized)
  4. Bridge — set up ``adb reverse tcp:<stream_port>``
  5. Ready — link to the Live page

The Tk page owns the widgets; this module owns the *state machine* so
its progression rules can be unit-tested without a display. The page calls
``step_status(state)`` to render the indicator chips and ``next_step(state)``
to pick which content frame to show.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.devices import Device, DeviceState

TOTAL_STEPS = 5

# Status of each step. The wizard only ever shows ONE step at a time
# (whichever is "current") so we don't expose "blocked" — uncompleted
# steps are simply "upcoming" until their turn.
STATUS_DONE = "done"
STATUS_CURRENT = "current"
STATUS_UPCOMING = "upcoming"


@dataclass
class OnboardingState:
    """Mutable snapshot the wizard uses to decide what to show next.

    Each field maps to one onboarding signal. None / empty defaults
    mean "user hasn't completed this step yet". The wizard mutates the
    fields in response to user actions and service callbacks (e.g.
    after a successful activate() the page sets ``has_activation=True``).
    """

    has_activation: bool = False
    selected_serial: str | None = None
    reverse_active: bool = False
    license_key_input: str = ""
    last_error: dict[int, str] = field(default_factory=dict)


def step_status(state: OnboardingState) -> dict[int, str]:
    """Return ``{step_number: status}``. The first non-done step is
    ``current``; everything after is ``upcoming``."""
    completed: set[int] = set()
    if state.has_activation:
        completed |= {1, 2}
    if state.has_activation and state.selected_serial:
        completed.add(3)
    if state.has_activation and state.selected_serial and state.reverse_active:
        completed.add(4)
    out: dict[int, str] = {}
    current_assigned = False
    for step in range(1, TOTAL_STEPS + 1):
        if step in completed:
            out[step] = STATUS_DONE
        elif not current_assigned:
            out[step] = STATUS_CURRENT
            current_assigned = True
        else:
            out[step] = STATUS_UPCOMING
    return out


def current_step(state: OnboardingState) -> int:
    """Step number the wizard should display right now."""
    for step, status in step_status(state).items():
        if status == STATUS_CURRENT:
            return step
    return TOTAL_STEPS  # all done → linger on the celebration step


def is_complete(state: OnboardingState) -> bool:
    """All four prerequisites done — step 5 is ready to launch."""
    statuses = step_status(state)
    return all(statuses[i] == STATUS_DONE for i in (1, 2, 3, 4))


def step_label(step: int) -> str:
    """Thai title for each step — single source of truth for the chip
    + page header text so they never drift apart."""
    return {
        1: "ใส่ License Key",
        2: "Activate",
        3: "เลือกอุปกรณ์",
        4: "Bridge (adb reverse)",
        5: "พร้อมไลฟ์",
    }.get(step, "?")


def authorized_devices(devices: list[Device]) -> list[Device]:
    """Filter that hides devices the wizard can't use."""
    return [d for d in devices if d.state == DeviceState.DEVICE]


def best_device_to_recommend(devices: list[Device]) -> Device | None:
    """Pick the first authorized device for the wizard's auto-select.
    Mirror behaviour of the legacy Studio UI which defaulted to whichever
    phone the customer plugged in first."""
    auth = authorized_devices(devices)
    return auth[0] if auth else None
