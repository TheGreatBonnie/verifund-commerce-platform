from buyer_agent.planner import mandate_from_text


def test_buyer_prompt_tells_the_model_the_only_changes_it_may_request():
    """The counter allowlist has to be in the prompt, or the model invents keys.

    A model that asks for one unsupported change loses the whole counter:
    the response is rejected and the buyer falls back to a scripted decision.
    """
    from buyer_agent.planner import BUYER_SYSTEM_PROMPT

    prompt = BUYER_SYSTEM_PROMPT
    assert "only changes" in prompt.lower()
    for key in (
        "warranty_months",
        "split_shipment",
        "shipping_cents",
        "delivery_days",
    ):
        assert key in prompt
    assert "target_unit_price_cents" in prompt


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


def test_mandate_from_text_grounds_the_category_from_the_catalog_product():
    mandate = mandate_from_text(
        "Negotiate for 2 units of the MacBook Air.",
        [
            {
                "sku": "EX-MACBOOK-AIR",
                "name": "MacBook Air",
                "category": "MacBook",
                "seller": "Northwind Audio",
                "description": "Lightweight laptop",
            }
        ],
    )

    assert mandate.product_sku == "EX-MACBOOK-AIR"
    assert mandate.category == "MacBook"


def test_mandate_from_text_reads_a_stated_quantity():
    mandate = mandate_from_text("Negotiate for the MacBook Air, quantity 2.")

    assert mandate.quantity == 2


def test_mandate_from_text_accepts_a_bare_sku_label():
    """The handoff brief may name the SKU without the 'Product ' prefix."""
    mandate = mandate_from_text("Negotiate for the MacBook Air. SKU: EX-MACBOOK-AIR.")

    assert mandate.product_sku == "EX-MACBOOK-AIR"


def test_mandate_from_text_accepts_an_item_sku_label():
    mandate = mandate_from_text("Negotiate for the MacBook Air. Item SKU: EX-MACBOOK-AIR")

    assert mandate.product_sku == "EX-MACBOOK-AIR"
