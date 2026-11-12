# Verifund Agreement and PayPal Checkout HITL Cards — Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the agreement and PayPal checkout HITL cards to match the reference information architecture, backed by a versioned product-metadata block flowing from seller catalog → offer → award → agreement terms → console, with cards rendering the hashed terms rather than demo copy.

**Architecture:** Keep the existing agreement lifecycle order. Add a required-but-tolerant `attributes` field to `AwardLineItem`, version the offer binding so pre-change hashes stay verifiable, propagate catalog metadata through `SellerPolicy.for_product` and the buyer's award builder, pass the full agreement projection into the checkout HITL args, style the cards with `mm-` rules in `globals.css`, and extract a shared `ProductSummary` component.

**Tech Stack:** Python (FastAPI/Pydantic, LangGraph, pytest), TypeScript/React (Next.js, zod, Vitest, Testing Library), Tailwind with the console's `--paper`/`--panel`/`--ink`/`--signal` token set.

**Spec:** `docs/superpowers/specs/2026-11-04-verifund-agreement-checkout-cards-enhancement.md`

## Global Constraints

- Agreement lifecycle order is unchanged: award approval → `create_settlement_award` → Verifund `create_agreement` → seller review → buyer approval → funding → checkout.
- `attributes` is required on `AwardLineItem` and on console agreement items; a before-validator injects `{}` for legacy payloads. Individual keys may be absent.
- `binding_version` defaults to 1 (legacy shape) and is 2 for everything created after this change. Verification dispatches on the declared version. Never hash v2 data with v1 rules or the reverse.
- No Tailwind palette utilities in the cards. All card styling is `mm-` classes in `apps/console/app/globals.css` using existing CSS variables.
- Chat rail is 340–398 px: single column, no horizontal overflow.
- Existing test IDs (`paypal-checkout`, `verifund-checkout-amount`, `agreement-approval-hitl`) must remain.
- Real PayPal flow (create/capture/poll/cancel/fallback/error) must remain intact.
- The checkout card total is `args.amount_cents` (the charged amount); the agreement total is a cross-check, never the displayed charge.
- Every test step must be green before its commit. No knowingly failing tests, no `|| true`, no swallowed exit codes.
- Run commands from the repo root. Python: `python -m pytest`. Console: `pnpm exec` inside `apps/console`.

---

## File Structure

- Modify: `packages/verifund_contracts/verifund_contracts/models.py` — `AwardLineItem.attributes` + validator, `AwardRequest.binding_version`.
- Modify: `packages/commerce_core/commerce_core/contracts.py` — `Offer.binding_version`.
- Modify: `packages/commerce_core/commerce_core/binding.py` — versioned binding, v1/v2.
- Modify: `packages/commerce_core/commerce_core/pricing.py` — `SellerPolicy` display fields, `for_product`, `catalog` fallback color.
- Modify: `apps/seller_agent/seller_agent/graph.py` — offer attributes, `binding_version=2`.
- Modify: `apps/buyer_agent/buyer_agent/settlement_flow.py` — propagate attributes and binding version.
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/generator.py` — `build_terms` emits attributes.
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/service.py` — `build_projection` round-trips attributes.
- Modify: `apps/orchestrator_agent/orchestrator_agent/verifund.py` — `_checkout_args` includes `agreement`.
- Modify: `apps/console/app/globals.css` — card rules.
- Modify: `apps/console/features/chat/verifund-tools.tsx` — schemas, helpers, `ProductSummary`, both cards.
- Modify: `apps/console/tests/features/chat/paypal-checkout-card.test.tsx` — agreement fixture, mismatch case.
- Create: `apps/console/tests/features/chat/agreement-approval-hitl.test.tsx`.
- Modify: `tests/unit/test_agreement_generator.py`, `tests/unit/test_offer_binding.py`, `tests/unit/test_verifund_contracts.py`, `tests/unit/test_seller_planner.py`, `tests/unit/test_buyer_settlement_flow.py`, `tests/unit/test_orchestrator_verifund.py`.

---

### Task 1: Model, tolerant `attributes`, versioned binding, terms, projection

**Files:**
- Modify: `packages/verifund_contracts/verifund_contracts/models.py:129`, `:256`
- Modify: `packages/commerce_core/commerce_core/contracts.py:106`
- Modify: `packages/commerce_core/commerce_core/binding.py:31-93`
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/generator.py:29-42`
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/service.py:721-772`

**Interfaces:**
- Produces: `AwardLineItem.attributes: dict[str, str]` required with a before-validator; `Offer.binding_version` and `AwardRequest.binding_version` (default 1); `canonical_offer_binding`/`binding_from_award` emitting v1 or v2 shape; term items always carrying `"attributes"`; `build_projection` passing `attributes=i.get("attributes") or {}` in both the list comprehension and the fallback line item.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_agreement_generator.py`, update the line item in `_award` and add an assertion to `test_build_terms_totals`:

```python
line_items=[AwardLineItem(sku="SKU-1", name="Sensor", quantity=10,
                          unit_price_cents=4200, warranty_addon_cents=300,
                          attributes={"color": "blue", "condition": "new"})],
```

```python
assert terms["items"][0]["attributes"] == {"color": "blue", "condition": "new"}
```

In `tests/unit/test_verifund_contracts.py`, add:

```python
def test_award_line_item_defaults_missing_attributes():
    from verifund_contracts.models import AwardLineItem

    item = AwardLineItem(
        sku="SKU-1", name="Sensor", quantity=1, unit_price_cents=100
    )
    assert item.attributes == {}


def test_award_accepts_a_legacy_payload_without_attributes():
    payload = award_payload()
    del payload["line_items"][0]["warranty_addon_cents"]
    request = AwardRequest(**payload)
    assert request.line_items[0].attributes == {}
    assert request.binding_version == 1
```

In `tests/unit/test_offer_binding.py`, add:

```python
def _v2_offer():
    offer = _offer()
    return offer.model_copy(
        update={
            "binding_version": 2,
            "line_items": [
                offer.line_items[0].model_copy(
                    update={"attributes": {"color": "#eaf0fb", "image_emoji": "💻"}}
                )
            ],
        }
    )


def _award_from(offer, binding_version: int) -> dict:
    return {
        "offer_id": offer.offer_id,
        "request_id": offer.request_id,
        "seller_id": offer.seller_id,
        "currency": "USD",
        "offer_round": offer.round,
        "offer_valid_until": offer.valid_until,
        "line_items": [i.model_dump(mode="json") for i in offer.line_items],
        "subtotal_cents": offer.subtotal_cents,
        "shipping_cents": offer.shipping_cents,
        "tax_cents": offer.tax_cents,
        "fees_cents": offer.fees_cents,
        "total_cents": offer.total_cents,
        "delivery_days": offer.delivery_days,
        "warranty_months": offer.warranty_months,
        "returns_days": offer.returns_days,
        "binding_version": binding_version,
    }


def test_v2_binding_binds_attributes_and_version():
    offer = _v2_offer()
    assert offer_hash(binding_from_award(_award_from(offer, 2))) == offer_hash(
        canonical_offer_binding(offer)
    )


def test_v1_verification_does_not_see_v2_attributes():
    offer = _v2_offer()
    assert offer_hash(binding_from_award(_award_from(offer, 1))) != offer_hash(
        canonical_offer_binding(offer)
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/unit/test_agreement_generator.py tests/unit/test_verifund_contracts.py tests/unit/test_offer_binding.py -q
```

Expected: FAIL — `attributes` is an unexpected keyword, `binding_version` is missing, and the v2 assertions do not exist yet.

- [ ] **Step 3: Implement**

`packages/verifund_contracts/verifund_contracts/models.py` — replace `AwardLineItem`:

```python
class AwardLineItem(VerifundModel):
    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)
    warranty_addon_cents: int = Field(default=0, ge=0)
    attributes: dict[str, str]

    @model_validator(mode="before")
    @classmethod
    def _default_attributes(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("attributes"):
            return {**data, "attributes": {}}
        return data
```

In `AwardRequest`, add alongside the other binding fields:

```python
binding_version: int = Field(default=1, ge=1)
```

In `packages/commerce_core/commerce_core/contracts.py`, add to `Offer`:

```python
binding_version: int = Field(default=1, ge=1)
```

`packages/commerce_core/commerce_core/binding.py`:

```python
BINDING_VERSION = 2


def _version_of(value: Any, fallback: int = 1) -> int:
    return int(getattr(value, "binding_version", fallback) or fallback)


def canonical_offer_binding(offer: Offer) -> dict[str, Any]:
    version = _version_of(offer)
    line_items = []
    for item in offer.line_items:
        payload = {
            "sku": item.sku,
            "name": item.name,
            "quantity": item.quantity,
            "unit_price_cents": item.unit_price_cents,
            "warranty_addon_cents": item.warranty_addon_cents,
        }
        if version >= 2:
            payload["attributes"] = dict(item.attributes or {})
        line_items.append(payload)
    binding: dict[str, Any] = {
        "offer_id": offer.offer_id,
        "request_id": offer.request_id,
        "seller_id": offer.seller_id,
        "currency": offer.currency.value if hasattr(offer.currency, "value") else str(offer.currency),
        "round": offer.round,
        "line_items": line_items,
        "subtotal_cents": offer.subtotal_cents,
        "shipping_cents": offer.shipping_cents,
        "tax_cents": offer.tax_cents,
        "fees_cents": offer.fees_cents,
        "total_cents": offer.total_cents,
        "delivery_days": offer.delivery_days,
        "warranty_months": offer.warranty_months,
        "returns_days": offer.returns_days,
        "offer_valid_until": _iso(offer.valid_until),
    }
    if version >= 2:
        binding["binding_version"] = version
    return binding


def binding_from_award(award: dict[str, Any]) -> dict[str, Any]:
    version = int(award.get("binding_version") or 1)
    line_items = []
    for item in award["line_items"]:
        payload = {
            "sku": item["sku"],
            "name": item["name"],
            "quantity": item["quantity"],
            "unit_price_cents": item["unit_price_cents"],
            "warranty_addon_cents": item.get("warranty_addon_cents", 0),
        }
        if version >= 2:
            payload["attributes"] = dict(item.get("attributes") or {})
        line_items.append(payload)
    subtotal = award.get("subtotal_cents")
    if subtotal is None:
        subtotal = sum(
            (item["unit_price_cents"] + item["warranty_addon_cents"]) * item["quantity"]
            for item in line_items
        )
    binding = {
        "offer_id": award["offer_id"],
        "request_id": award["request_id"],
        "seller_id": award["seller_id"],
        "currency": award["currency"],
        "round": award["offer_round"],
        "line_items": line_items,
        "subtotal_cents": subtotal,
        "shipping_cents": award["shipping_cents"],
        "tax_cents": award["tax_cents"],
        "fees_cents": award["fees_cents"],
        "total_cents": award.get("total_cents", award.get("amount_cents")),
        "delivery_days": award["delivery_days"],
        "warranty_months": award["warranty_months"],
        "returns_days": award["returns_days"],
        "offer_valid_until": _iso(award["offer_valid_until"]),
    }
    if version >= 2:
        binding["binding_version"] = version
    return binding
```

`apps/verifund_control_plane/verifund_control_plane/agreements/generator.py` `build_terms`:

```python
items.append({
    "sku": li.sku,
    "name": li.name,
    "quantity": li.quantity,
    "unit_price_cents": li.unit_price_cents,
    "warranty_addon_cents": li.warranty_addon_cents,
    "line_total_cents": line_total,
    "attributes": dict(li.attributes or {}),
})
```

`apps/verifund_control_plane/verifund_control_plane/agreements/service.py` `build_projection`:

```python
line_items = [
    AwardLineItem(
        sku=i.get("sku", ""),
        name=i.get("name", ""),
        quantity=i.get("quantity", 1),
        unit_price_cents=i.get("unit_price_cents", 0),
        warranty_addon_cents=i.get("warranty_addon_cents", 0),
        attributes=i.get("attributes") or {},
    )
    for i in items
]
```

and the fallback:

```python
line_items=line_items
if line_items
else [AwardLineItem(sku="x", name="x", quantity=1, unit_price_cents=1, attributes={})],
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/unit/test_agreement_generator.py tests/unit/test_verifund_contracts.py tests/unit/test_offer_binding.py tests/unit/test_agreement_service.py tests/unit/test_verifund_domain.py -q
```

Expected: PASS. `test_agreement_service.py` and `test_verifund_domain.py` are included because they build awards from dicts; the validator must carry them without edits.

- [ ] **Step 5: Commit**

```bash
git add packages/verifund_contracts/verifund_contracts/models.py \
  packages/commerce_core/commerce_core/contracts.py \
  packages/commerce_core/commerce_core/binding.py \
  apps/verifund_control_plane/verifund_control_plane/agreements/generator.py \
  apps/verifund_control_plane/verifund_control_plane/agreements/service.py \
  tests/unit/test_agreement_generator.py tests/unit/test_offer_binding.py \
  tests/unit/test_verifund_contracts.py
git commit -m "feat(verifund): version the offer binding and bind product attributes"
```

---

### Task 2: Seller catalog metadata reaches the offer

**Files:**
- Modify: `packages/commerce_core/commerce_core/pricing.py:12-40`, `:69-110`, `:117-155`
- Modify: `apps/seller_agent/seller_agent/graph.py:320-342`

**Interfaces:**
- Consumes: `SellerCatalogProduct` (`description`, `image_emoji`, `tag`, `color`, `color_name`).
- Produces: `SellerPolicy.product_description`, `image_emoji`, `product_tag`, `product_color`; offer line item `attributes` with `color` (hex), `color_name`, `description`, `image_emoji`, `condition`, `category`, `tag`, `specs`; `binding_version=2`.

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_seller_planner.py`, add:

```python
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from commerce_core.pricing import Quote
from seller_agent.graph import _offer_from_quote
from seller_agent.planner import SellerDecision


def test_for_product_carries_catalog_metadata(northwind_policy):
    policy = northwind_policy.for_product("MM-MACBOOK-AIR-M4-13")
    assert policy.product_description == "Apple M4 · 16GB memory · 256GB SSD · Space Gray"
    assert policy.image_emoji == "💻"
    assert policy.product_color == "#eaf0fb"
    assert policy.color == "gray"


def test_offer_attributes_describe_the_selected_product(northwind_policy):
    policy = northwind_policy.for_product("MM-MACBOOK-AIR-M4-13")
    quote = Quote(
        base_unit_price_cents=97900,
        warranty_addon_cents=0,
        unit_price_cents=97900,
        subtotal_cents=97900,
        total_cents=97900,
        delivery_days=5,
        stock_confidence=0.9,
        split_shipment=False,
        warranty_months=12,
        valid_until=datetime.now(UTC) + timedelta(hours=1),
    )
    offer = _offer_from_quote(
        policy=policy,
        state={
            "task_id": "task-1",
            "context_id": "context-1",
            "rfq": SimpleNamespace(request_id="rfq-1", quantity=1),
            "previous_offer": None,
            "current_round": 1,
        },
        quote=quote,
        decision=SellerDecision(
            action="propose",
            unit_price_cents=97900,
            warranty_months=12,
            rationale="test",
        ),
    )
    attributes = offer.line_items[0].attributes
    assert attributes["image_emoji"] == "💻"
    assert attributes["color"] == "#eaf0fb"
    assert attributes["color_name"] == "gray"
    assert attributes["specs"] == "Apple M4 · 16GB memory · 256GB SSD · Space Gray"
    assert attributes["category"] == "Electronics"
    assert offer.binding_version == 2
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/unit/test_seller_planner.py -q
```

Expected: FAIL — `product_description` and `product_color` do not exist, and the offer only carries `color`.

- [ ] **Step 3: Implement**

`packages/commerce_core/commerce_core/pricing.py`, add to `SellerPolicy` after `product_name`:

```python
product_description: str = ""
image_emoji: str = "📦"
product_tag: str = ""
product_color: str = "#eef2ed"
```

In `for_product`, add to the `update` dict:

```python
"product_description": product.description,
"image_emoji": product.image_emoji,
"product_tag": product.tag,
"product_color": product.color,
```

In the `catalog()` single-product branch, keep `color` safe:

```python
color=self.color if self.color.startswith("#") else "#eef2ed",
color_name=self.color,
```

`apps/seller_agent/seller_agent/graph.py` `_offer_from_quote`, replace the line item:

```python
line_item = OfferLineItem(
    sku=policy.sku,
    name=policy.product_name,
    quantity=quantity,
    unit_price_cents=quote.base_unit_price_cents,
    list_unit_price_cents=policy.list_unit_price_cents,
    warranty_addon_cents=quote.warranty_addon_cents,
    attributes={
        "color": policy.product_color,
        "color_name": policy.color,
        "description": policy.product_description or policy.product_name,
        "image_emoji": policy.image_emoji,
        "condition": "new",
        "category": policy.categories[0] if policy.categories else "",
        "tag": policy.product_tag,
        "specs": policy.product_description or policy.product_name,
    },
)
```

and pass `binding_version=2` to the `Offer(...)` constructor in the same function.

No store change is needed: `save_offer` persists `offer.model_dump(mode="json")` and `get_offer` re-validates it, so `binding_version` and the attributes round-trip, and pre-change rows default to version 1.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/unit/test_seller_planner.py tests/unit/test_seller_agreement_review.py tests/unit/test_contracts.py tests/protocol/test_seller_orders.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/pricing.py apps/seller_agent/seller_agent/graph.py tests/unit/test_seller_planner.py
git commit -m "feat(seller): carry catalog metadata into offer attributes"
```

---

### Task 3: Buyer award propagation

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/settlement_flow.py:34-101`

**Interfaces:**
- Consumes: winning offer line items carrying `attributes`, and `binding_version`.
- Produces: an `AwardRequest` whose line items carry `attributes` and whose `binding_version` matches the offer, so `create_from_award`'s `offer_hash(binding_from_award(award.model_dump()))` equals the seller's hash.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_buyer_settlement_flow.py`, add:

```python
from commerce_core.binding import binding_from_award, offer_hash

ATTRIBUTES = {"color": "#eaf0fb", "image_emoji": "💻"}


def test_build_award_request_preserves_attributes_and_binding_version():
    payload = award_payload()
    payload["winner"].update(
        {
            "binding_version": 2,
            "line_items": [
                {
                    "sku": "NC-700",
                    "name": "MacBook Air M4 13-inch",
                    "quantity": 12,
                    "unit_price_cents": 10000,
                    "warranty_addon_cents": 0,
                    "attributes": ATTRIBUTES,
                }
            ],
        }
    )
    request = build_award_request("run-1", {"buyer_id": "demo-buyer"}, payload)
    assert request.binding_version == 2
    assert request.line_items[0].attributes == ATTRIBUTES
    assert offer_hash(binding_from_award(request.model_dump(mode="json"))) == request.offer_hash


def test_build_award_request_keeps_legacy_offers_on_v1():
    request = build_award_request("run-1", {"buyer_id": "demo-buyer"}, award_payload())
    assert request.binding_version == 1
    assert request.line_items[0].attributes == {}
    assert offer_hash(binding_from_award(request.model_dump(mode="json"))) == request.offer_hash
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/unit/test_buyer_settlement_flow.py -q
```

Expected: FAIL — attributes are dropped and the award has no binding version, so the recomputed hash does not match.

- [ ] **Step 3: Implement**

In `build_award_request`, add `attributes` and `binding_version` to the normalized offer dict:

```python
    normalized = {
        "offer_id": winner["offer_id"],
        ...
        "binding_version": winner.get("binding_version", 1),
        "line_items": [
            {
                "sku": item["sku"],
                "name": item["name"],
                "quantity": item["quantity"],
                "unit_price_cents": item["unit_price_cents"],
                "list_unit_price_cents": item.get(
                    "list_unit_price_cents", item["unit_price_cents"]
                ),
                "warranty_addon_cents": item.get("warranty_addon_cents", 0),
                "attributes": item.get("attributes") or {},
            }
            for item in winner["line_items"]
        ],
        ...
    }
```

And in the `AwardRequest(...)` constructor:

```python
        line_items=[
            AwardLineItem(
                sku=item["sku"],
                name=item["name"],
                quantity=item["quantity"],
                unit_price_cents=item["unit_price_cents"],
                warranty_addon_cents=item.get("warranty_addon_cents", 0),
                attributes=item.get("attributes") or {},
            )
            for item in winner["line_items"]
        ],
        binding_version=winner.get("binding_version", 1),
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/unit/test_buyer_settlement_flow.py tests/integration/test_buyer_settlement_api.py -q
```

Expected: PASS. The legacy test must stay green, which is the point of the v1 default.

- [ ] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/settlement_flow.py tests/unit/test_buyer_settlement_flow.py
git commit -m "feat(buyer): propagate product attributes and binding version into awards"
```

---

### Task 4: Orchestrator checkout args and console schemas

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/verifund.py:1011-1024`
- Modify: `apps/console/features/chat/verifund-tools.tsx:29-84`
- Modify: `apps/console/tests/features/chat/paypal-checkout-card.test.tsx:48-58`
- Modify: `tests/unit/test_orchestrator_verifund.py`

**Interfaces:**
- Produces: `_checkout_args` includes `agreement`; `agreementSchema` item requires `attributes`; `paypalCheckoutArgsSchema` requires `agreement`.

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_orchestrator_verifund.py`, add:

```python
def test_checkout_args_carry_the_agreement_projection() -> None:
    result = task_result(
        skill=VerifundSkill.TRANSACTION_FUND,
        data={
            **binding(),
            "transaction_id": AGREEMENT.transaction_id,
            "amount_cents": AGREEMENT.amount_cents,
            "currency": "USD",
        },
    )
    args = VerifundLifecycle._checkout_args(cast(Any, None), result)
    assert args["agreement"] == binding()["agreement"]
    assert args["amount_cents"] == AGREEMENT.amount_cents
```

In `apps/console/tests/features/chat/paypal-checkout-card.test.tsx`, add `agreement` to `ARGS`:

```ts
  agreement: {
    agreement_id: "agr_1",
    agreement_version: 1,
    terms: {
      parties: { seller: { display_name: "NovaTech" } },
      items: [
        {
          sku: "NC-700",
          name: "Nimbus NC-700 ANC Headset",
          quantity: 12,
          unit_price_cents: 10000,
          warranty_addon_cents: 0,
          attributes: { color: "#eef2ed", image_emoji: "🎧", condition: "new" },
        },
      ],
      totals: {
        currency: "USD",
        subtotal_cents: 120000,
        shipping_cents: 3400,
        tax_cents: 0,
        fees_cents: 0,
        total_cents: 123400,
      },
      inspection: { period_hours: 48 },
    },
  },
```

No assertion changes yet: the card still renders `args.amount_cents`, so the existing `$3,400.00` test remains green.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/unit/test_orchestrator_verifund.py -q -k checkout
```

Expected: FAIL — `args["agreement"]` is `None`.

- [ ] **Step 3: Implement**

`_checkout_args`:

```python
    @staticmethod
    def _checkout_args(
        handle: VerifundTaskHandle, result: VerifundTaskResult
    ) -> dict[str, Any]:
        data = result.data or {}
        return {
            "transaction_id": data.get("transaction_id"),
            "amount_cents": data.get("amount_cents"),
            "currency": data.get("currency"),
            "expires_at": data.get("expires_at"),
            "agreement": data.get("agreement"),
            "message": (
                result.message
                or "Complete the PayPal checkout to fund this transaction."
            ),
        }
```

`verifund-tools.tsx` `agreementSchema` item:

```ts
    line_items: z.array(
      z.object({
        sku: z.string(),
        name: z.string(),
        quantity: z.number().int().positive(),
        unit_price_cents: z.number().int().positive(),
        warranty_addon_cents: z.number().int().nonnegative().default(0),
        attributes: z.record(z.string()),
      }),
    ),
```

`paypalCheckoutArgsSchema`:

```ts
export const paypalCheckoutArgsSchema = z.object({
  transaction_id: z.string().min(1),
  amount_cents: z.number().int().positive(),
  currency: z.string().min(1),
  expires_at: z.string().optional(),
  agreement: z.record(z.unknown()),
  message: z
    .string()
    .default("Complete the PayPal checkout to fund this transaction."),
});
```

- [ ] **Step 4: Run the tests and typecheck**

```bash
python -m pytest tests/unit/test_orchestrator_verifund.py -q
cd apps/console && pnpm exec tsc --noEmit
```

Expected: PASS and no type errors.

- [ ] **Step 5: Record the rollout constraint**

Append to the task notes (not the code): **deploy only when no runs are parked at `await_checkout`.** Those runs carry a persisted HITL payload without `agreement`, and the now-required schema will refuse to render their card. Runs at `await_funding_approval` are unaffected because that payload already includes `agreement`.

- [ ] **Step 6: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/verifund.py \
  apps/console/features/chat/verifund-tools.tsx \
  apps/console/tests/features/chat/paypal-checkout-card.test.tsx \
  tests/unit/test_orchestrator_verifund.py
git commit -m "feat(verifund): pass the agreement into checkout HITL args"
```

---

### Task 5: `mm-` card styles

**Files:**
- Modify: `apps/console/app/globals.css` (insert before `/* ---------- Alert / footer ---------- */`, currently line 2881)

**Interfaces:**
- Produces classes used by Tasks 6–8: `mm-product*`, `mm-money*`, `mm-inspection*`, `mm-card-section`, `mm-acceptance*`, `mm-digest`, `mm-trust*`, `mm-amount-warning`, `mm-status-pill`.

- [ ] **Step 1: Add the rules**

```css
/* ---------- Verifund product, terms, and checkout cards ---------- */

.mm-approval .mm-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
  padding: 3px 6px;
  border: 1px solid var(--signal);
  color: var(--signal);
  font-size: 8px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.mm-approval .mm-status-pill.is-amber {
  border-color: var(--amber);
  color: var(--amber);
}

.mm-approval .mm-status-pill.is-muted {
  border-color: var(--rule-strong);
  color: var(--muted);
}

.mm-approval .mm-product {
  display: flex;
  gap: 10px;
  margin-top: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--rule);
}

.mm-approval .mm-product-tile {
  display: grid;
  place-items: center;
  width: 64px;
  height: 56px;
  flex: 0 0 auto;
  overflow: hidden;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--panel-green);
  font-size: 24px;
  line-height: 1;
}

.mm-approval .mm-product-tile img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.mm-approval .mm-product-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  flex: 1;
}

.mm-approval .mm-product-name {
  margin: 0;
  color: var(--ink);
  font-size: 11.5px;
  font-weight: 600;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.mm-approval .mm-product-seller {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 0;
  color: var(--muted);
  font-size: 9px;
}

.mm-approval .mm-product-seller svg {
  color: var(--signal);
  flex: 0 0 auto;
}

.mm-approval .mm-product-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 2px 0 0;
  padding: 0;
  list-style: none;
}

.mm-approval .mm-product-chips li {
  padding: 2px 5px;
  border: 1px solid var(--rule);
  background: var(--panel);
  color: var(--ink-soft);
  font-size: 8.5px;
  line-height: 1.3;
}

.mm-approval .mm-product-qty {
  margin: 0;
  color: var(--muted);
  font-size: 9px;
}

.mm-approval .mm-product-qty strong {
  color: var(--ink);
  font-family: var(--font-spline-sans-mono), monospace;
  font-weight: 600;
}

.mm-approval .mm-money {
  padding: 10px 0;
  border-bottom: 1px solid var(--rule);
}

.mm-approval .mm-money-label {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 0 0 6px;
  color: var(--signal);
  font-size: 7.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.mm-approval .mm-money-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 2px 0;
  color: var(--muted);
  font-size: 9.5px;
}

.mm-approval .mm-money-row strong {
  color: var(--ink);
  font-family: var(--font-spline-sans-mono), monospace;
  font-weight: 600;
}

.mm-approval .mm-money-total {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--rule);
}

.mm-approval .mm-money-total span:first-child {
  color: var(--ink);
  font-size: 10px;
  font-weight: 600;
}

.mm-approval .mm-money-total strong {
  color: var(--signal-deep);
  font-family: var(--font-spline-sans-mono), monospace;
  font-size: 19px;
  letter-spacing: -0.04em;
}

.mm-approval .mm-money-total em {
  color: var(--muted);
  font-size: 8px;
  font-style: normal;
}

.mm-approval .mm-inspection {
  margin-top: 10px;
  padding: 8px;
  border: 1px solid var(--rule);
  background: var(--panel-green);
}

.mm-approval .mm-inspection-grid {
  display: grid;
  gap: 6px;
  margin: 0;
}

.mm-approval .mm-inspection-grid dt {
  color: var(--muted);
  font-size: 8px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.mm-approval .mm-inspection-grid dd {
  margin: 1px 0 0;
  color: var(--ink-soft);
  font-size: 9.5px;
  line-height: 1.45;
}

.mm-approval .mm-inspection .mm-check-list {
  margin-top: 2px;
}

.mm-approval details.mm-card-section {
  padding: 8px 0;
  border-bottom: 1px solid var(--rule);
}

.mm-approval details.mm-card-section > summary {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--ink);
  font-size: 10px;
  font-weight: 600;
  cursor: pointer;
  list-style: none;
}

.mm-approval details.mm-card-section > summary::-webkit-details-marker {
  display: none;
}

.mm-approval details.mm-card-section > summary::after {
  content: "+";
  margin-left: auto;
  color: var(--signal);
  font-family: var(--font-spline-sans-mono), monospace;
}

.mm-approval details.mm-card-section[open] > summary::after {
  content: "–";
}

.mm-approval details.mm-card-section > *:not(summary) {
  margin-top: 6px;
}

.mm-approval .mm-acceptance {
  display: flex;
  flex-direction: column;
  margin: 0;
}

.mm-approval .mm-acceptance-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 3px 0;
  border-bottom: 1px dashed var(--rule);
  color: var(--ink-soft);
  font-size: 9.5px;
}

.mm-approval .mm-acceptance-row:last-child {
  border-bottom: 0;
}

.mm-approval .mm-acceptance-row strong {
  font-size: 9px;
  font-weight: 600;
}

.mm-approval .mm-acceptance-row strong.is-ok {
  color: var(--signal);
}

.mm-approval .mm-acceptance-row strong.is-pending {
  color: var(--amber);
}

.mm-approval .mm-digest {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  align-items: center;
  margin: 0;
  color: var(--muted);
  font-family: var(--font-spline-sans-mono), monospace;
  font-size: 8px;
}

.mm-approval .mm-digest strong {
  color: var(--ink-soft);
  font-weight: 600;
}

.mm-approval .mm-trust {
  display: grid;
  gap: 6px;
  margin-top: 10px;
  padding: 8px;
  border: 1px solid var(--rule);
  background: var(--panel-green);
}

.mm-approval .mm-trust-head {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 0;
  color: var(--ink-soft);
  font-size: 9.5px;
  line-height: 1.45;
}

.mm-approval .mm-trust-head svg {
  color: var(--signal);
  flex: 0 0 auto;
}

.mm-approval .mm-trust-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--rule);
  color: var(--muted);
  font-size: 8px;
  text-align: center;
}

.mm-approval .mm-trust-grid span {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}

.mm-approval .mm-trust-grid svg {
  color: var(--signal);
}

.mm-approval .mm-amount-warning {
  margin-top: 6px;
  padding: 5px 6px;
  border: 1px solid var(--amber);
  color: var(--amber);
  font-size: 8.5px;
  line-height: 1.4;
}
```

- [ ] **Step 2: Verify the stylesheet compiles**

```bash
cd apps/console && pnpm build 2>&1 | tail -20
```

Expected: build succeeds. If a full build is too slow, `pnpm exec tsc --noEmit` plus a browser look at the rail is acceptable; note which check was used.

- [ ] **Step 3: Commit**

```bash
git add apps/console/app/globals.css
git commit -m "feat(console): add mm- styles for the Verifund agreement and checkout cards"
```

---

### Task 6: Helpers and shared `ProductSummary`

**Files:**
- Modify: `apps/console/features/chat/verifund-tools.tsx` (after the existing `money` helper, before `AgreementApprovalHitlCard`)

**Interfaces:**
- Produces: `agreementTerms`, `agreementItems`, `labelFor`, `hexColor`, `formatStamp`, `ProductSummary` with `data-testid="product-summary"`.

- [ ] **Step 1: Add the helpers**

```tsx
const EVIDENCE_LABELS: Record<string, string> = {
  shipment_manifest: "Shipment manifest",
  delivery_confirmation: "Delivery confirmation",
  invoice: "Invoice",
  other: "Other evidence",
};

const REMEDY_LABELS: Record<string, string> = {
  cancel_and_refund: "Cancel and full refund",
  refund_or_replacement: "Refund or replacement",
};

function labelFor(map: Record<string, string>, value: unknown) {
  const key = String(value ?? "");
  return map[key] ?? key.replaceAll("_", " ");
}

function hexColor(value: unknown): string | null {
  return typeof value === "string" &&
    /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(value)
    ? value
    : null;
}

function agreementTerms(agreement: any): Record<string, any> {
  const terms = agreement?.terms;
  return terms && typeof terms === "object" ? terms : {};
}

function agreementItems(agreement: any): any[] {
  const items = agreementTerms(agreement).items ?? agreement?.line_items ?? [];
  return Array.isArray(items) ? items : [];
}

function formatStamp(value: unknown): string | null {
  if (!value) return null;
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(date);
}
```

- [ ] **Step 2: Add `ProductSummary`**

```tsx
function ProductSummary({ agreement }: { agreement: any }) {
  const items = agreementItems(agreement);
  const item = items[0] ?? {};
  const attrs = (item.attributes ?? {}) as Record<string, any>;
  const terms = agreementTerms(agreement);
  const sellerName =
    terms?.parties?.seller?.display_name ??
    agreement?.seller_id ??
    "Seller";
  const name = item.name ?? "Agreement item";
  const quantity = agreement?.quantity ?? item.quantity ?? 1;
  const warranty = agreement?.warranty_months ?? terms.warranty_months;
  const returns = agreement?.returns_days ?? terms.returns_days;
  const inspectionHours =
    agreement?.inspection_period_hours ?? terms?.inspection?.period_hours;
  const specs = String(attrs.specs ?? "")
    .split("·")
    .map((part) => part.trim())
    .filter(Boolean);
  const chips = [
    attrs.condition,
    ...specs,
    warranty ? `${warranty}-month warranty` : null,
    returns ? `${returns}-day returns` : null,
    inspectionHours ? `${inspectionHours}-hour inspection` : null,
  ].filter((chip): chip is string => Boolean(chip));
  const visible = chips.slice(0, 4);
  const overflow = chips.length - visible.length;
  const tileColor = hexColor(attrs.color);

  return (
    <div className="mm-product" data-testid="product-summary">
      <div
        className="mm-product-tile"
        style={tileColor ? { backgroundColor: tileColor } : undefined}
      >
        {attrs.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={String(attrs.image_url)} alt={String(name)} />
        ) : (
          <span aria-hidden="true">{attrs.image_emoji || "📦"}</span>
        )}
      </div>
      <div className="mm-product-body">
        <h4 className="mm-product-name">
          {String(name)}
          {items.length > 1 ? ` (+${items.length - 1} more)` : ""}
        </h4>
        <p className="mm-product-seller">
          {String(sellerName)}
          <BadgeCheck size={12} aria-label="Verified seller" />
        </p>
        <ul className="mm-product-chips">
          {visible.map((chip, index) => (
            <li key={`${chip}-${index}`}>{chip}</li>
          ))}
          {overflow > 0 ? <li>+{overflow} more</li> : null}
        </ul>
        <p className="mm-product-qty">
          Quantity <strong>{String(quantity)}</strong>
        </p>
      </div>
    </div>
  );
}
```

Add the lucide import at the top of the file (the file currently imports none):

```tsx
import {
  BadgeCheck,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileCheck2,
  Info,
  LockKeyhole,
  ShieldCheck,
  Truck,
  WalletCards,
} from "lucide-react";
```

- [ ] **Step 3: Typecheck**

```bash
cd apps/console && pnpm exec tsc --noEmit
```

Expected: no errors. The helpers and component are unused at this point, which TypeScript does not flag.

- [ ] **Step 4: Commit**

```bash
git add apps/console/features/chat/verifund-tools.tsx
git commit -m "feat(console): add shared ProductSummary and agreement helpers"
```

---

### Task 7: Rebuild `AgreementApprovalHitlCard`

**Files:**
- Modify: `apps/console/features/chat/verifund-tools.tsx:809-944`

**Interfaces:**
- Consumes: `args.agreement` (projection with `terms`), `args.version`, `args.digest`, `args.seller_decision`, `args.precheck`, `args.review_url`, `args.handle`.
- Produces: card with product summary, money rows, inspection, collapsed obligations/returns/acceptance/digest, note, three actions.

**Do not** re-add a second const block for `url` or `pc`; both already exist in this component. Replace the existing const block in place, then replace the `return (...)`.

- [ ] **Step 1: Replace the const block**

Replace from `const a = ...` through `const pc = args?.precheck;` (lines 822-839) with:

```tsx
  const a = (args?.agreement ?? {}) as Record<string, any>;
  const id = String(a.agreement_id ?? a.id ?? "");
  const version = Number(args?.version ?? a.current_version ?? a.agreement_version ?? 1);
  const hash = String(args?.digest ?? a.agreement_hash ?? a.version?.agreement_hash ?? "");
  const handle: ResumeHandle | null =
    args?.handle?.task_id && args?.handle?.context_id && args?.handle?.run_id
      ? {
          task_id: args.handle.task_id,
          context_id: args.handle.context_id,
          run_id: args.handle.run_id,
        }
      : null;
  const url = args?.review_url ?? a.review_url;
  const seller = args?.seller_decision ?? a.seller_decision;
  const pc = args?.precheck;

  const terms = agreementTerms(a);
  const totals = (terms.totals ?? {}) as Record<string, any>;
  const currency = String(totals.currency ?? a.currency ?? "USD");
  const inspection = (terms.inspection ?? {}) as Record<string, any>;
  const delivery = (terms.delivery ?? {}) as Record<string, any>;
  const remedies = (terms.remedies ?? {}) as Record<string, any>;
  const evidence = Array.isArray(terms.evidence_required)
    ? terms.evidence_required
    : [];
  const approved = a.status === "AGREED";
  const expiresAt = formatStamp(a.expires_at);
  const sellerStatus =
    typeof seller === "string"
      ? seller
      : seller?.status ?? seller?.decision ?? "Accepted";
  const precheckStatus = pc
    ? typeof pc === "string"
      ? pc
      : pc.recommendation ?? pc.status
    : null;
```

Leave `const decide = async (...) => {...}` untouched.

- [ ] **Step 2: Replace the `return (...)`**

```tsx
  return (
    <section data-testid="agreement-approval-hitl" className="mm-approval">
      <div className="mm-verifund-head">
        <div>
          <p className="mm-kicker">Verifund agreement</p>
          <h3>
            <span>{id || "Agreement"}</span>
          </h3>
        </div>
        {approved ? (
          <span className="mm-status-pill">
            <CheckCircle2 size={11} /> Approved
          </span>
        ) : (
          <span className="mm-status-pill is-amber">
            <Clock3 size={11} /> Awaiting your approval
          </span>
        )}
      </div>

      <div className="mm-verifund-detail">
        <div>
          <p className="mm-kicker">Version</p>
          <strong>v{version}</strong>
        </div>
        <div>
          <p className="mm-kicker">Expires</p>
          <strong>{expiresAt ?? "Not set"}</strong>
        </div>
      </div>

      <div data-testid="agreement-product-summary">
        <ProductSummary agreement={a} />
      </div>

      <div className="mm-money" data-testid="agreement-money-rows">
        <p className="mm-money-label">Agreed commercial terms</p>
        <div className="mm-money-row">
          <span>Product price</span>
          <strong>
            {money(Number(totals.subtotal_cents ?? a.amount_cents ?? 0), currency)}
          </strong>
        </div>
        <div className="mm-money-row">
          <span>Tracked shipping</span>
          <strong>{money(Number(totals.shipping_cents ?? 0), currency)}</strong>
        </div>
        <div className="mm-money-row">
          <span>Taxes</span>
          <strong>{money(Number(totals.tax_cents ?? 0), currency)}</strong>
        </div>
        <div className="mm-money-row">
          <span>Fees</span>
          <strong>{money(Number(totals.fees_cents ?? 0), currency)}</strong>
        </div>
        <div className="mm-money-total">
          <span>Total payable</span>
          <strong>
            {money(Number(totals.total_cents ?? a.amount_cents ?? 0), currency)}{" "}
            <em>{currency}</em>
          </strong>
        </div>
      </div>

      <div className="mm-inspection" data-testid="agreement-inspection-panel">
        <p className="mm-money-label">
          <Clock3 size={11} /> Inspection and verification
        </p>
        <dl className="mm-inspection-grid">
          <div>
            <dt>Inspection window</dt>
            <dd>
              {inspection.period_hours ?? a.inspection_period_hours ?? 0} hours
              after {String(inspection.starts_on ?? "delivery").replaceAll("_", " ").toLowerCase()}
            </dd>
          </div>
          <div>
            <dt>Verification checklist</dt>
            <dd>
              <ul className="mm-check-list">
                {evidence.length ? (
                  evidence.map((item: string) => (
                    <li key={item}>
                      <CheckCircle2 size={11} />
                      {labelFor(EVIDENCE_LABELS, item)}
                    </li>
                  ))
                ) : (
                  <li>No evidence requirements listed</li>
                )}
              </ul>
            </dd>
          </div>
        </dl>
      </div>

      <details className="mm-card-section">
        <summary>
          <ShieldCheck size={12} /> Seller obligations
        </summary>
        <ul className="mm-check-list">
          <li>
            <CheckCircle2 size={11} /> Match the agreed product specifications
          </li>
          <li>
            <CheckCircle2 size={11} /> Provide tracked shipping within{" "}
            {delivery.delivery_days ?? a.delivery_days ?? 0} days
          </li>
          <li>
            <CheckCircle2 size={11} /> Maintain a{" "}
            {terms.warranty_months ?? a.warranty_months ?? 0}-month warranty
          </li>
        </ul>
      </details>

      <details className="mm-card-section">
        <summary>
          <Info size={12} /> Returns and disputes
        </summary>
        <div className="mm-acceptance">
          <div className="mm-acceptance-row">
            <span>Not delivered</span>
            <strong>
              {remedies.non_delivery
                ? labelFor(REMEDY_LABELS, remedies.non_delivery)
                : "Not specified"}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Late delivery</span>
            <strong>
              {remedies.late_delivery
                ? labelFor(REMEDY_LABELS, remedies.late_delivery)
                : "Not specified"}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Damaged goods</span>
            <strong>
              {remedies.damaged_goods
                ? labelFor(REMEDY_LABELS, remedies.damaged_goods)
                : "Not specified"}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Returns window</span>
            <strong>{terms.returns_days ?? a.returns_days ?? 0} days</strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Dispute window</span>
            <strong>{terms.dispute_window_hours ?? 0} hours</strong>
          </div>
        </div>
        {url ? (
          <a href={url} target="_blank" rel="noopener noreferrer">
            Open full agreement <ChevronRight size={11} />
          </a>
        ) : null}
      </details>

      <details className="mm-card-section">
        <summary>
          <FileCheck2 size={12} /> Agreement acceptance
        </summary>
        <div className="mm-acceptance">
          <div className="mm-acceptance-row">
            <span>Seller Agent</span>
            <strong className="is-ok">{String(sellerStatus)}</strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Buyer</span>
            <strong className="is-pending">
              {approved ? "Approved" : "Awaiting approval"}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Verifund</span>
            <strong className="is-ok">Validated</strong>
          </div>
          {precheckStatus ? (
            <div className="mm-acceptance-row">
              <span>Precheck</span>
              <strong>{String(precheckStatus)}</strong>
            </div>
          ) : null}
        </div>
      </details>

      <details className="mm-card-section">
        <summary>
          <LockKeyhole size={12} /> Agreement digest
        </summary>
        <p className="mm-digest">
          <strong>{String(hash).slice(0, 16) || "unavailable"}</strong>
          <span>Created {formatStamp(a.created_at) ?? "unknown"}</span>
          <span>v{version}</span>
        </p>
      </details>

      <label className="mm-note-field">
        Note
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={pending}
        />
      </label>

      <div className="mm-approval-actions mm-approval-actions-split">
        <button
          type="button"
          className="mm-button mm-button-signal mm-approval-primary"
          disabled={pending}
          onClick={() => decide(approveAgreement, "APPROVE")}
        >
          {pending ? "Working…" : "Approve"}
        </button>
        <button
          type="button"
          className="mm-button mm-button-outline-danger"
          disabled={pending}
          onClick={() => decide(rejectAgreement, "REJECT")}
        >
          Reject
        </button>
        <button
          type="button"
          className="mm-button mm-button-outline"
          disabled={pending}
          onClick={() => decide(requestChangesAgreement, "REQUEST_CHANGES")}
        >
          Request changes
        </button>
      </div>

      {error ? (
        <p role="alert" data-testid="agreement-hitl-error">
          {error}
        </p>
      ) : null}

      <p className="mm-approval-prompt">
        Approval applies only to agreement {id}, version v{version}.
      </p>
    </section>
  );
```

- [ ] **Step 3: Typecheck**

```bash
cd apps/console && pnpm exec tsc --noEmit
```

Expected: no errors. If TS reports a redeclaration of `url` or `pc`, the old const block was not fully replaced.

- [ ] **Step 4: Commit**

```bash
git add apps/console/features/chat/verifund-tools.tsx
git commit -m "feat(console): render the agreement card from the hashed terms"
```

---

### Task 8: Rebuild `PayPalCheckoutCard`

**Files:**
- Modify: `apps/console/features/chat/verifund-tools.tsx:669-789`

**Interfaces:**
- Consumes: `args` with required `agreement`, `respond`, `onVerifundAction`.
- Produces: header, product summary, order summary with server-authoritative total and mismatch warning, trust panel, payment method, fine print.

Leave `phase`, `error`, `busy`, `decide`, `base`, `pollUntilFunded`, and `approve` untouched.

- [ ] **Step 1: Add derived values** after `const busy = ...`:

```tsx
  const agreement = args.agreement as Record<string, any>;
  const terms = agreementTerms(agreement);
  const totals = (terms.totals ?? {}) as Record<string, any>;
  const currency = String(totals.currency ?? args.currency ?? "USD");
  const agreementId = String(agreement.agreement_id ?? "");
  const agreementVersion = Number(agreement.agreement_version ?? 1);
  const inspection = (terms.inspection ?? {}) as Record<string, any>;
  const evidence = Array.isArray(terms.evidence_required)
    ? terms.evidence_required
    : [];
  const agreementTotal = Number(totals.total_cents ?? args.amount_cents);
  const amountMismatch = agreementTotal !== args.amount_cents;
```

- [ ] **Step 2: Replace the `return (...)`**

```tsx
  return (
    <section className="mm-approval" data-testid="paypal-checkout">
      <div className="mm-verifund-head">
        <div>
          <p className="mm-kicker">Verifund checkout</p>
          <h3>
            <span>Secure checkout</span>
          </h3>
        </div>
        <span
          className={`mm-status-pill${phase === "ready" ? " is-amber" : ""}`}
        >
          <LockKeyhole size={11} />
          {phase === "ready" ? "Secure payment" : "Payment confirmed"}
        </span>
      </div>

      <p className="mm-approval-prompt">
        Payment for agreement {agreementId} · v{agreementVersion}
      </p>

      <div data-testid="checkout-product-summary">
        <ProductSummary agreement={agreement} />
      </div>

      <div className="mm-money" data-testid="checkout-order-summary">
        <p className="mm-money-label">Order summary</p>
        <div className="mm-money-row">
          <span>Product price</span>
          <strong>
            {money(
              Number(totals.subtotal_cents ?? args.amount_cents),
              currency,
            )}
          </strong>
        </div>
        <div className="mm-money-row">
          <span>Tracked shipping</span>
          <strong>{money(Number(totals.shipping_cents ?? 0), currency)}</strong>
        </div>
        <div className="mm-money-row">
          <span>Taxes</span>
          <strong>{money(Number(totals.tax_cents ?? 0), currency)}</strong>
        </div>
        <div className="mm-money-total">
          <span>Total payable</span>
          <strong data-testid="verifund-checkout-amount">
            {money(args.amount_cents, currency)} <em>{currency}</em>
          </strong>
        </div>
        {amountMismatch ? (
          <p className="mm-amount-warning" data-testid="checkout-amount-mismatch">
            The agreement total is {money(agreementTotal, currency)}; the amount
            being charged is {money(args.amount_cents, currency)}.
          </p>
        ) : null}
      </div>

      <div className="mm-trust" data-testid="checkout-trust-panel">
        <p className="mm-trust-head">
          <ShieldCheck size={14} />
          <span>
            Payment is processed through PayPal and recorded against agreement{" "}
            {agreementId}. Fulfillment is evaluated against the agreed
            verification conditions.
          </span>
        </p>
        <div className="mm-trust-grid">
          <span>
            <Truck size={14} /> Tracked delivery
          </span>
          <span>
            <Clock3 size={14} />
            {inspection.period_hours ?? "—"}-hour inspection
          </span>
          <span>
            <ShieldCheck size={14} /> {evidence.length} verification rules
          </span>
        </div>
      </div>

      <div className="mm-money">
        <p className="mm-money-label">Payment method</p>
        {phase === "fallback" ? (
          <div>
            <p className="mm-approval-prompt">
              PayPal is unavailable in this browser.
            </p>
            <button
              type="button"
              className="mm-button"
              onClick={() => decide({ status: "fallback", ...base() })}
            >
              Pay on PayPal&apos;s site
            </button>
          </div>
        ) : (
          <PayPalProvider
            clientId={process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID ?? ""}
            environment={
              process.env.NEXT_PUBLIC_PAYPAL_ENVIRONMENT === "production"
                ? "production"
                : "sandbox"
            }
            components={["paypal-payments"]}
            pageType="checkout"
          >
            <PayPalOneTimePaymentButton
              presentationMode="auto"
              disabled={busy}
              createOrder={async () => {
                const { id } = await createOrderAction({
                  transactionId: args.transaction_id,
                });
                return { orderId: id };
              }}
              onApprove={approve}
              onCancel={() => decide({ status: "canceled", ...base() })}
              onError={() => setPhase("fallback")}
            />
          </PayPalProvider>
        )}
        {busy ? <p className="mm-approval-prompt">Confirming payment…</p> : null}
        {phase === "error" && error ? <p role="alert">{error}</p> : null}
        {args.expires_at ? (
          <p className="mm-mono-note">Offer expires at {args.expires_at}</p>
        ) : null}
      </div>

      <p className="mm-approval-prompt">
        <Info size={11} /> By continuing, you authorize payment for the
        transaction described in the approved Verifund agreement.
      </p>
    </section>
  );
```

- [ ] **Step 3: Typecheck**

```bash
cd apps/console && pnpm exec tsc --noEmit
```

Expected: no errors. `args.agreement_version` is deliberately absent; the version comes from `agreement.agreement_version`.

- [ ] **Step 4: Commit**

```bash
git add apps/console/features/chat/verifund-tools.tsx
git commit -m "feat(console): rebuild checkout card with order summary and trust panel"
```

---

### Task 9: Card tests

**Files:**
- Modify: `apps/console/tests/features/chat/paypal-checkout-card.test.tsx`
- Create: `apps/console/tests/features/chat/agreement-approval-hitl.test.tsx`

- [ ] **Step 1: Add the checkout assertions**

```tsx
  it("renders the agreement-derived product and the charged amount", () => {
    setup();
    expect(screen.getByTestId("checkout-product-summary")).toHaveTextContent(
      "Nimbus NC-700 ANC Headset",
    );
    expect(screen.getByTestId("verifund-checkout-amount")).toHaveTextContent(
      "$3,400.00",
    );
  });

  it("flags a divergence between the agreement total and the charge", () => {
    setup({
      agreement: {
        ...ARGS.agreement,
        terms: {
          ...ARGS.agreement.terms,
          totals: {
            ...ARGS.agreement.terms.totals,
            total_cents: 340100,
          },
        },
      },
    });
    expect(screen.getByTestId("checkout-amount-mismatch")).toHaveTextContent(
      "$3,401.00",
    );
    expect(screen.getByTestId("verifund-checkout-amount")).toHaveTextContent(
      "$3,400.00",
    );
  });
```

- [ ] **Step 2: Create the agreement card test**

```tsx
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AgreementApprovalHitlCard } from "@/features/chat/verifund-tools";

const HASH = "a".repeat(64);

const agreement = {
  agreement_id: "agr_1",
  agreement_version: 1,
  transaction_id: "vf_1",
  currency: "USD",
  amount_cents: 123400,
  quantity: 12,
  status: "PENDING_BUYER",
  expires_at: "2026-11-05T12:00:00Z",
  created_at: "2026-11-04T12:00:00Z",
  agreement_hash: HASH,
  line_items: [
    {
      sku: "NC-700",
      name: "Nimbus NC-700 ANC Headset",
      quantity: 12,
      unit_price_cents: 10000,
      warranty_addon_cents: 0,
      attributes: {
        color: "#eef2ed",
        color_name: "black",
        image_emoji: "🎧",
        condition: "new",
        specs: "Adaptive audio · 30-hour battery",
      },
    },
  ],
  terms: {
    parties: { seller: { display_name: "NovaTech" } },
    items: [
      {
        sku: "NC-700",
        name: "Nimbus NC-700 ANC Headset",
        quantity: 12,
        unit_price_cents: 10000,
        warranty_addon_cents: 0,
        attributes: { image_emoji: "🎧", condition: "new" },
      },
    ],
    totals: {
      currency: "USD",
      subtotal_cents: 120000,
      shipping_cents: 3400,
      tax_cents: 0,
      fees_cents: 0,
      total_cents: 123400,
    },
    inspection: { period_hours: 48, starts_on: "DELIVERY_CONFIRMED" },
    delivery: { delivery_days: 7, starts_on: "FUNDING_CONFIRMED" },
    warranty_months: 24,
    returns_days: 30,
    dispute_window_hours: 72,
    evidence_required: ["shipment_manifest", "delivery_confirmation", "invoice"],
    remedies: {
      non_delivery: "cancel_and_refund",
      late_delivery: "cancel_and_refund",
      damaged_goods: "refund_or_replacement",
    },
  },
};

const args = {
  agreement,
  version: 1,
  digest: HASH,
  seller_decision: { status: "accepted" },
  precheck: { recommendation: "pass" },
  review_url: "/agreements/agr_1",
};

describe("AgreementApprovalHitlCard", () => {
  it("renders the product summary and the terms-derived total", () => {
    render(<AgreementApprovalHitlCard args={args as any} respond={vi.fn()} />);
    expect(screen.getByTestId("agreement-approval-hitl")).toBeInTheDocument();
    expect(
      screen.getByTestId("agreement-product-summary"),
    ).toHaveTextContent("Nimbus NC-700 ANC Headset");
    expect(screen.getByTestId("agreement-money-rows")).toHaveTextContent(
      "$1,234.00",
    );
  });

  it("renders the inspection window and the agreed evidence", () => {
    render(<AgreementApprovalHitlCard args={args as any} respond={vi.fn()} />);
    const panel = screen.getByTestId("agreement-inspection-panel");
    expect(panel).toHaveTextContent("48 hours");
    expect(panel).toHaveTextContent("Delivery confirmation");
  });

  it("renders the agreement's remedy rather than demo copy", () => {
    render(<AgreementApprovalHitlCard args={args as any} respond={vi.fn()} />);
    const returns = screen
      .getByText("Returns and disputes")
      .closest("details") as HTMLDetailsElement;
    expect(returns.open).toBe(false);
    expect(within(returns).getByText("Refund or replacement")).toBeTruthy();
    expect(within(returns).getByText("72 hours")).toBeTruthy();
  });
});
```

- [ ] **Step 3: Run the tests**

```bash
cd apps/console && pnpm exec vitest run tests/features/chat
```

Expected: PASS, including the unchanged `$3,400.00` assertion.

- [ ] **Step 4: Commit**

```bash
git add apps/console/tests/features/chat
git commit -m "test(console): cover the terms-driven agreement and checkout cards"
```

---

### Task 10: Full verification

- [ ] **Step 1: Console typecheck and tests**

```bash
cd apps/console && pnpm exec tsc --noEmit
cd apps/console && pnpm test
```

Expected: no type errors; all suites pass.

- [ ] **Step 2: Backend tests**

```bash
python -m pytest tests/unit/test_offer_binding.py tests/unit/test_agreement_generator.py \
  tests/unit/test_agreement_service.py tests/unit/test_verifund_contracts.py \
  tests/unit/test_verifund_domain.py tests/unit/test_buyer_settlement_flow.py \
  tests/unit/test_seller_planner.py tests/unit/test_seller_agreement_review.py \
  tests/unit/test_orchestrator_verifund.py -q
```

Expected: PASS.

- [ ] **Step 3: Confirm no palette literals remain in the cards**

```bash
grep -nE "(bg|text|border)-(slate|blue|emerald|amber|red|zinc|gray)-[0-9]" apps/console/features/chat/verifund-tools.tsx
```

Expected: no matches.

- [ ] **Step 4: Check the worktree**

```bash
git status --short
```

If the only entries are the files listed in this plan, the work is complete. Do not commit unrelated changes.

---

## Self-Review Notes

- **Spec coverage:** tolerant `attributes` (Task 1), versioned binding (Task 1), seller catalog metadata (Task 2), buyer propagation (Task 3), checkout args and schemas (Task 4), `mm-` styles (Task 5), shared summary (Task 6), agreement card (Task 7), checkout card (Task 8), tests (Task 9), verification (Task 10).
- **Removed from revision 1:** the false claim that the binding hash is unchanged for attribute-less offers; the amount-only checkout fallback; hardcoded obligations/remedies/verification copy; the `getattr`-based seller metadata guesses; per-component `money` helpers; the deliberately failing Task 3 test; the `2>/dev/null || true` verification step; machine-absolute paths.
- **Type consistency:** `attributes` is `dict[str, str]` on the wire and `z.record(z.string())` in the console; `binding_version` is an `int` in both models; `ProductSummary` reads `terms.items` with a `line_items` fallback in both cards; `money(cents, currency)` is the single currency helper.
- **Open risk, not a plan step:** the `mm-` styles have no automated coverage. The suites prove structure and content; the rail needs one manual look after Task 5.
