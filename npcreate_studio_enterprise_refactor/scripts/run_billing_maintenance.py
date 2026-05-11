from __future__ import annotations

from npcreate_backend.jobs import run_billing_maintenance
from npcreate_backend.settings import BackendSettings


def main() -> None:
    print(run_billing_maintenance(BackendSettings()))


if __name__ == "__main__":
    main()
