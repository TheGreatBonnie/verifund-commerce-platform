"""Deterministic product-type groups for category filtering.

The marketplace taxonomy is split: laptops arrive as either ``Laptop`` or
``MacBook``, and peripherals are spread across ``Keyboard``, ``Mouse`` and
``Office Accessory``. A single exact ``category`` value therefore cannot
express "laptops", so the orchestrator passes the shopper's own term and this
map resolves it to every category that term covers.

Keep this list aligned with the seeded catalog categories in
``docs/templates/*.yaml``. Unknown terms resolve to ``None`` and the caller
falls back to exact matching, so a stale entry never widens a filter silently.
"""

from __future__ import annotations

CATEGORY_GROUPS: dict[str, tuple[str, ...]] = {
    "laptop": ("Laptop", "MacBook"),
    "laptops": ("Laptop", "MacBook"),
    "notebook": ("Laptop", "MacBook"),
    "notebooks": ("Laptop", "MacBook"),
    "computer": ("Laptop", "MacBook", "Gaming PC"),
    "computers": ("Laptop", "MacBook", "Gaming PC"),
    "macbook": ("MacBook",),
    "monitor": ("Monitor",),
    "monitors": ("Monitor",),
    "keyboard": ("Keyboard",),
    "keyboards": ("Keyboard",),
    "mouse": ("Mouse",),
    "mice": ("Mouse",),
    "gaming pc": ("Gaming PC",),
    "desk": ("Standing Desk",),
    "desks": ("Standing Desk",),
    "standing desk": ("Standing Desk",),
    "chair": ("Ergonomic Chair",),
    "chairs": ("Ergonomic Chair",),
    "office accessory": ("Office Accessory",),
    "laptop accessory": ("Laptop Accessory",),
    "creative tools": ("Creative Tools",),
}


def resolve_categories(term: str | None) -> tuple[str, ...] | None:
    """Return the catalog categories covered by a shopper-facing type term."""
    if not term:
        return None
    key = " ".join(term.casefold().split())
    return CATEGORY_GROUPS.get(key)
