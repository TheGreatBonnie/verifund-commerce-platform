from commerce_core.scoring import (
    hard_constraint_failures,
    rank_offers,
)


def test_circuitforge_wins_final_comparison(mandate, final_offers):
    ranking = rank_offers(mandate, final_offers)
    assert ranking[0].offer.seller_id == "circuitforge"
    assert ranking[0].score > ranking[1].score


def test_initial_offers_have_expected_failures(mandate, initial_offers):
    by_seller = {o.seller_id: o for o in initial_offers}
    assert "warranty" in " ".join(
        hard_constraint_failures(mandate, by_seller["circuitforge"])
    ).lower()
    assert "stock" in " ".join(
        hard_constraint_failures(mandate, by_seller["aurora-supply"])
    ).lower()
    assert "budget" in " ".join(
        hard_constraint_failures(mandate, by_seller["northwind-audio"])
    ).lower()
