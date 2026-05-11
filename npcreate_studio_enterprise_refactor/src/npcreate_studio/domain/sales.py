from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ShopSummary:
    shop_id: str
    revenue_cents: int
    orders: int
    generated_at: datetime
