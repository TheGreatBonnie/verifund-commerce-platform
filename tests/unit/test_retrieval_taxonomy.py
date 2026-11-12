from __future__ import annotations

from commerce_core.retrieval.taxonomy import resolve_categories


def test_laptop_resolves_to_both_laptop_categories():
    assert resolve_categories("laptop") == ("Laptop", "MacBook")


def test_resolution_ignores_case_and_surrounding_space():
    assert resolve_categories("  LAPTOP  ") == ("Laptop", "MacBook")


def test_specific_terms_resolve_to_a_single_category():
    assert resolve_categories("MacBook") == ("MacBook",)
    assert resolve_categories("Standing Desk") == ("Standing Desk",)


def test_unknown_terms_do_not_resolve():
    assert resolve_categories("spaceship") is None
    assert resolve_categories("   ") is None
    assert resolve_categories(None) is None
