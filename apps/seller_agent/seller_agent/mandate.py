from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SellerMandate:
    version: int = 1
    auto_accept: bool = True
    allowed_currencies: list[str] = field(default_factory=lambda: ["USD"])
    max_total_cents: int = 500000
    min_warranty_months: int = 0
    max_warranty_months: int = 24
    min_returns_days: int = 0
    max_returns_days: int = 60
    max_inspection_period_hours: int = 72
    max_dispute_window_hours: int = 168

    def allows(self, *, currency="USD", total_cents=0, warranty_months=0,
               returns_days=0, inspection_period_hours=0,
               dispute_window_hours=0) -> bool:
        if currency not in self.allowed_currencies:
            return False
        if total_cents > self.max_total_cents:
            return False
        if not (self.min_warranty_months <= warranty_months <= self.max_warranty_months):
            return False
        if not (self.min_returns_days <= returns_days <= self.max_returns_days):
            return False
        if inspection_period_hours > self.max_inspection_period_hours:
            return False
        if dispute_window_hours > self.max_dispute_window_hours:
            return False
        return True


def load_mandate(profile: dict[str, Any]) -> SellerMandate:
    raw = profile.get("mandate") or {}
    return SellerMandate(**{k: v for k, v in raw.items() if k in SellerMandate.__dataclass_fields__})
