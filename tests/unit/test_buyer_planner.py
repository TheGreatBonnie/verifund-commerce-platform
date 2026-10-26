from buyer_agent.planner import mandate_from_text


def test_marketplace_sku_trailing_sentence_period_is_not_part_of_sku():
    mandate = mandate_from_text(
        "Find and negotiate the best terms for Smartwatch Series 10. "
        "Product SKU: MM-SMARTWATCH-SERIES-10. "
        "Product details: GPS watch."
    )

    assert mandate.product_sku == "MM-SMARTWATCH-SERIES-10"


def test_sku_with_internal_period_keeps_it():
    mandate = mandate_from_text("Product SKU: MODEL.2-PRO.")

    assert mandate.product_sku == "MODEL.2-PRO"
