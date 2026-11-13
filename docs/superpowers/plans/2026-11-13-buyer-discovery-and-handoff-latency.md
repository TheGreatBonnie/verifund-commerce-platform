# Buyer Discovery and Handoff Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Buyer find registered sellers on every handoff, and cut the orchestrator→Buyer handoff from ~180 s to a bounded few seconds.

**Architecture:** Two independent defects stack. (1) The Buyer asks the registry for sellers in category `consumer-electronics`, a category no seller is indexed under, and the registry filters categories by exact equality — so discovery returns zero sellers even though the seller is registered and healthy. (2) The Buyer's first node makes a live LLM call whose `45 s` timeout is multiplied by an SDK retry and a 2-iteration loop, so a failed brief parse costs ~180 s before the deterministic fallback runs. The fix grounds the brief against the published catalog first (deterministic, ~0.3 s), so the product identity and category the registry indexes are known without the LLM, and bounds the LLM attempt to one try.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), LangGraph, pydantic v2, LangChain `ChatOpenAI`; Next.js 16 + vitest for the console.

**Spec:** This document. The diagnosis was reproduced against the live deployment (`gateway-795m.onrender.com`) and is summarised in "Context" below.

## Context (measured, live)

- Registered seller categories: `Accessories, Audio, Creative Tools, Ergonomic Chair, Keyboard, Laptop, Laptop Accessory, MacBook, Monitor, Office Accessory, Standing Desk, Storage, Wearable`. No `consumer-electronics`.
- `POST /registry/v1/discover` with `category=consumer-electronics` → 0 sellers. With `category=Monitor` → 1 seller. With `category=consumer-electronics` **and** `product_sku=EX-MACBOOK-AIR` → 1 seller.
- The orchestrator sent the Buyer `SKU: EX-MACBOOK-AIR.` The Buyer's `SKU_PATTERN` requires the literal label `Product SKU:`, so `product_sku` was `null`, the category filter applied, and `discover_sellers` returned `"No independently validated sellers were found."`
- Buyer brief-parse latency, measured from UUIDv6 checkpoint timestamps in the `buyer` database: `interpret_brief` took **182.45 s**, **117 s**, **191.8 s**, and **6.1 s** on the fast path. Discovery itself took **0.18 s**.

## Global Constraints

- Backend work lands on branch **`deploy/render`**; console work lands on branch **`deploy/console`**. The branches have diverged — do not mix files across them.
- **No worktrees.** Work directly in the tree on the correct branch and commit there.
- Backend tests: `.venv/bin/python -m pytest tests/unit tests/protocol`. Console tests: `pnpm test` from `apps/console`.
- Python style: `ruff`, line length 100, `target-version = "py312"`.
- Every production change in this plan is preceded by a failing test that is watched to fail.
- The registry's category vocabulary is whatever sellers register. The Buyer must never invent a category outside it.
- `MARKETMESH_LLM_MODE=live` and `NEBIUS_*` come from the Render `gateway-shared` env-var group, which the Render REST env-var API does not expose. They are set — the code must work under `live` mode.

---

## Track A — Backend (`deploy/render`)

### Task 1: Registry discovery tolerates categories it does not index

The registry filters sellers with `if not product_sku and category not in seller["categories"]: continue`. Two changes: compare case-insensitively, and only enforce a category the registry actually knows. A caller using a category outside the registry's vocabulary gets every extension-matching seller instead of an empty result set — silently returning nothing makes a naming difference look like a supply outage.

**Files:**
- Modify: `apps/registry/registry/store.py:217-252` (`RegistryStore.discover`)
- Modify: `apps/registry/registry/store.py` (module level, add helpers)
- Create: `tests/unit/test_registry_discovery.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: module-level `registry.store._fold_category(value: str) -> str` and `registry.store._category_matches(categories: list[str], category: str) -> bool`.

- [x] **Step 1: Write the failing tests**

Create `tests/unit/test_registry_discovery.py`:

```python
"""Discovery must never hide a registered seller behind a category naming difference."""
from __future__ import annotations

import pytest
from commerce_core.extension import EXTENSION_URI
from registry.store import RegistryStore
from sqlalchemy.ext.asyncio import create_async_engine


CARD_JSON = {
    "name": "Northwind Audio",
    "version": "1.0.0",
    "capabilities": {
        "streaming": True,
        "extensions": [{"uri": EXTENSION_URI, "required": True, "params": {}}],
    },
}


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}")
    registry = RegistryStore(engine)
    await registry.create_schema()
    await registry.upsert(
        seller_id="northwind-audio",
        name="Northwind Audio",
        card_url="http://127.0.0.1:9201/.well-known/agent-card.json",
        categories=["Audio", "MacBook"],
        card_json=CARD_JSON,
        card_hash="hash-1",
        healthy=True,
        error=None,
    )
    await registry.upsert(
        seller_id="circuitforge",
        name="CircuitForge",
        card_url="http://127.0.0.1:9202/.well-known/agent-card.json",
        categories=["Keyboard"],
        card_json=CARD_JSON,
        card_hash="hash-2",
        healthy=True,
        error=None,
    )
    yield registry
    await engine.dispose()


async def test_discover_narrows_to_the_sellers_indexed_under_a_known_category(store):
    found = await store.discover("Audio", EXTENSION_URI)

    assert [row["seller_id"] for row in found] == ["northwind-audio"]


async def test_discover_matches_a_known_category_case_insensitively(store):
    found = await store.discover("audio", EXTENSION_URI)

    assert [row["seller_id"] for row in found] == ["northwind-audio"]


async def test_discover_does_not_hide_sellers_behind_an_unknown_category(store):
    found = await store.discover("consumer-electronics", EXTENSION_URI)

    assert sorted(row["seller_id"] for row in found) == [
        "circuitforge",
        "northwind-audio",
    ]


async def test_discover_ignores_an_empty_category(store):
    found = await store.discover("", EXTENSION_URI)

    assert sorted(row["seller_id"] for row in found) == [
        "circuitforge",
        "northwind-audio",
    ]
```

- [x] **Step 2: Run the tests to verify they fail**

```
cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a
.venv/bin/python -m pytest tests/unit/test_registry_discovery.py -q
```

Expected: the case-insensitive test fails (`found == []`), and the unknown-category and empty-category tests fail (`found == []`).

- [x] **Step 3: Implement**

In `apps/registry/registry/store.py`, add at module level (below the imports):

```python
def _fold_category(value: str) -> str:
    """Normalise a category for comparison: case and spacing insensitive."""
    return " ".join((value or "").strip().casefold().split())


def _category_matches(categories: list[str], category: str) -> bool:
    """Whether a seller's categories contain the requested category."""
    needle = _fold_category(category)
    if not needle:
        return True
    return any(_fold_category(entry) == needle for entry in categories or [])
```

In `RegistryStore.discover`, replace the seller loop with:

```python
        sellers = await self.list_sellers()
        # The registry only narrows by a category it actually indexes. A caller
        # that asks for a category outside the registry's vocabulary gets every
        # extension-matching seller rather than an empty result set: silently
        # returning nothing makes a naming difference look like a supply
        # outage.
        enforce_category = any(
            _fold_category(entry) == _fold_category(category)
            for seller in sellers
            for entry in seller.get("categories", []) or []
            if _fold_category(category)
        )
        for seller in sellers:
            if not seller.get("verified", True):
                continue
            if enforce_category and not _category_matches(
                seller["categories"], category
            ):
                continue
            if listing_sellers is not None and seller["seller_id"] not in listing_sellers:
                continue
            extensions = (
                seller["card_json"].get("capabilities", {}).get("extensions", [])
            )
            if not any(
                extension.get("uri") == extension_uri
                for extension in extensions
            ):
                continue
            found.append(seller)
            if len(found) >= limit:
                break
        return found
```

Keep the `product_sku` listing lookup that already precedes this block.

- [x] **Step 4: Run the tests to verify they pass**

```
.venv/bin/python -m pytest tests/unit/test_registry_discovery.py -q
```

Expected: all pass.

- [x] **Step 5: Run the full backend suite for regressions**

```
.venv/bin/python -m pytest tests/unit tests/protocol -q
```

Expected: no new failures. (Pre-existing unrelated failures: `tests/unit/test_shared_review_store.py::test_reviews_are_org_scoped` and three in `tests/unit/test_verifund_seller_reads.py` — these are SQLite-only failures that predate this work.)

- [x] **Step 6: Commit**

```bash
git add apps/registry/registry/store.py tests/unit/test_registry_discovery.py
git commit -m "fix(registry): match discovery categories case-insensitively and never hide sellers behind an unknown category"
```

---

### Task 2: The Buyer grounds the brief against the published catalog

`interpret_brief` calls `planner.parse_brief(text)` with no catalog, so the SKU is only ever found by the literal `Product SKU:` regex and the category is the hard-coded `"consumer-electronics"`. The registry already publishes the catalog the sellers are indexed by, so the Buyer resolves the brief against it instead of guessing.

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/planner.py` (`mandate_from_text`, `NebiusBuyerPlanner.parse_brief`, add `ground_mandate`)
- Modify: `apps/buyer_agent/buyer_agent/graph.py:175-257` (`interpret_brief`, add `_catalog_products`)
- Test: `tests/unit/test_buyer_brief_parsing.py`, `tests/unit/test_buyer_planner.py`

**Interfaces:**
- Consumes: `buyer_agent.planner.retrieve_candidates(brief_text: str, products: list[dict], limit: int = 3) -> list[dict]` (existing).
- Produces:
  - `buyer_agent.planner.ground_mandate(mandate: Mandate, text: str, products: list[dict[str, Any]] | None) -> Mandate`
  - `buyer_agent.planner.mandate_from_text(text: str, products: list[dict[str, Any]] | None = None) -> Mandate` — now grounds `category` as well as `product_sku`.

- [x] **Step 1: Write the failing tests**

Append to `tests/unit/test_buyer_brief_parsing.py`:

```python
class FakeRegistry:
    def __init__(self, products: list[dict[str, Any]]) -> None:
        self._products = products

    async def marketplace_products(self, **_: Any) -> list[dict[str, Any]]:
        return self._products


CATALOG = [
    {
        "sku": "EX-MACBOOK-AIR",
        "name": "MacBook Air",
        "category": "MacBook",
        "seller": "Northwind Audio",
        "description": "Lightweight laptop",
    }
]


async def test_interpret_brief_grounds_sku_and_category_from_the_catalog() -> None:
    trace = FakeTrace()
    services = SimpleNamespace(trace=trace, registry=FakeRegistry(CATALOG))
    state = cast(
        BuyerState,
        {
            "messages": [
                HumanMessage(
                    content=(
                        "Negotiate for this product. SKU: EX-MACBOOK-AIR. "
                        "Name: MacBook Air. Unit price: $1,199.99."
                    )
                )
            ]
        },
    )
    config = {"configurable": {"thread_id": "run-1", "services": services}}

    result = await interpret_brief(state, config)

    assert result["mandate"]["product_sku"] == "EX-MACBOOK-AIR"
    assert result["mandate"]["category"] == "MacBook"


async def test_interpret_brief_grounds_the_catalog_when_the_planner_fails() -> None:
    trace = FakeTrace()
    services = SimpleNamespace(trace=trace, registry=FakeRegistry(CATALOG))
    state = cast(
        BuyerState,
        {
            "messages": [
                HumanMessage(content="Negotiate for the MacBook Air, quantity 2.")
            ]
        },
    )
    config = {"configurable": {"thread_id": "run-1", "services": services}}

    result = await interpret_brief(state, config)

    assert result["mandate"]["product_sku"] == "EX-MACBOOK-AIR"
    assert result["mandate"]["category"] == "MacBook"
```

Append to `tests/unit/test_buyer_planner.py`:

```python
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
```

- [x] **Step 2: Run the tests to verify they fail**

```
.venv/bin/python -m pytest tests/unit/test_buyer_brief_parsing.py tests/unit/test_buyer_planner.py -q
```

Expected: the new tests fail — `product_sku` is `None` and `category` is `"consumer-electronics"`.

- [x] **Step 3: Implement the planner changes**

In `apps/buyer_agent/buyer_agent/planner.py`, replace the catalog branch inside `mandate_from_text`:

```python
    product_hint = product_match.group(1).strip() if product_match else "Nimbus NC-700 ANC Headset"
    product_sku = sku_match.group(1) if sku_match else None
    category = "consumer-electronics"
    candidates = retrieve_candidates(text, products) if products is not None else []
    if candidates:
        top = candidates[0]
        if not product_sku:
            sku = top.get("sku")
            if sku:
                product_sku = str(sku)
        name = top.get("name")
        if name:
            product_hint = str(name)
        # The catalog carries the category the registry indexes sellers under.
        # A category invented here would hide every seller behind the
        # registry's discovery filter.
        grounded = str(top.get("category") or "").strip()
        if grounded:
            category = grounded
    return Mandate(
        run_id="demo-run",
        category=category,
        ...
    )
```

Also widen the quantity match so a stated quantity survives the fallback. The
current pattern only recognises `"2 units"`; a brief that says `"quantity 2"`
silently falls back to twelve units:

```python
    quantity_match = re.search(
        r"\b(\d{1,3})\s+(?:x\s+)?(?:Nimbus|units?|headsets?)"
        r"|\b(?:quantity|qty)\b\s*[:=]?\s*(\d{1,4})",
        text,
        re.IGNORECASE,
    )
    ...
    quantity = (
        int(quantity_match.group(1) or quantity_match.group(2))
        if quantity_match
        else (1 if sku_match else 12)
    )
```

Add at module level in `planner.py`:

```python
def ground_mandate(
    mandate: Mandate, text: str, products: list[dict[str, Any]] | None
) -> Mandate:
    """Resolve a mandate's product identity against the published catalog.

    The catalog is the source of truth for the identifiers the registry
    indexes, so it wins over anything the brief parser guessed.
    """
    if not products:
        return mandate
    candidates = retrieve_candidates(text, products)
    if not candidates:
        return mandate
    top = candidates[0]
    updates: dict[str, Any] = {}
    if not mandate.product_sku and top.get("sku"):
        updates["product_sku"] = str(top["sku"])
    grounded = str(top.get("category") or "").strip()
    if grounded:
        updates["category"] = grounded
    if not updates:
        return mandate
    return mandate.model_copy(update=updates)
```

In `NebiusBuyerPlanner.parse_brief`, delete the whitelist clamp:

```python
        # The registry indexes sellers under the catalog's own categories, so
        # a category the model invents is dropped rather than forced onto a
        # value that matches no seller.
        if mandate.category not in _known_categories:
            mandate = mandate.model_copy(update={"category": ""})
        return mandate
```

Replace it with:

```python
        # The model's category is a guess, and forcing it onto a fixed value
        # is what hid every seller from discovery. The catalog is the
        # authority on categories; the registry ignores a category it does
        # not index, and `ground_mandate` replaces this one with the
        # catalog's.
        return mandate
```

Do not reintroduce a hard-coded category vocabulary anywhere: the registry
derives its categories from what sellers publish, so a copy of that list in
the buyer is a second source of truth that drifts.

- [x] **Step 4: Implement the graph changes**

In `apps/buyer_agent/buyer_agent/graph.py`, add a module-level helper above `interpret_brief`:

```python
async def _catalog_products(services: Any) -> list[dict[str, Any]]:
    """The published catalog, used to ground a brief against real products.

    Discovery can only name products and categories the registry indexes, so
    the brief is resolved against the catalog rather than a guess. A catalog
    that cannot be read leaves the brief ungrounded instead of failing.
    """
    registry = getattr(services, "registry", None)
    marketplace_products = getattr(registry, "marketplace_products", None)
    if marketplace_products is None:
        return []
    try:
        return list(await marketplace_products())
    except Exception:  # noqa: BLE001
        return []
```

In `interpret_brief`, replace the planner loop and fallback:

```python
    planner = _planner(config, ScriptedBuyerPlanner())
    services = _services(config)
    products = await _catalog_products(services)
    mandate = None
    fallback_used = False
    for _ in range(2):
        try:
            mandate = await planner.parse_brief(text, products)
            if not isinstance(mandate, Mandate):
                mandate = Mandate.model_validate(mandate)
            break
        except Exception:  # noqa: BLE001
            mandate = None
    if mandate is None:
        fallback_used = True
        try:
            mandate = mandate_from_text(text, products)
        except Exception as exc:  # noqa: BLE001
            ...
    mandate = mandate.model_copy(update={"run_id": run_id})
    mandate = ground_mandate(mandate, text, products)
    sku_match = re.search(SKU_PATTERN, text, re.IGNORECASE)
    if sku_match:
        mandate = mandate.model_copy(update={"product_sku": sku_match.group(1)})
```

Add `ground_mandate` to the `from buyer_agent.planner import (...)` block.

- [x] **Step 5: Run the tests to verify they pass**

```
.venv/bin/python -m pytest tests/unit/test_buyer_brief_parsing.py tests/unit/test_buyer_planner.py -q
```

Expected: all pass, including the pre-existing `test_marketplace_sku_trailing_sentence_period_is_not_part_of_sku` and `test_sku_with_internal_period_keeps_it`.

- [x] **Step 6: Run the full backend suite**

```
.venv/bin/python -m pytest tests/unit tests/protocol -q
```

Expected: no new failures.

- [x] **Step 7: Commit**

```bash
git add apps/buyer_agent/buyer_agent/planner.py apps/buyer_agent/buyer_agent/graph.py \
  tests/unit/test_buyer_brief_parsing.py tests/unit/test_buyer_planner.py
git commit -m "fix(buyer): ground the sourcing brief against the published catalog so discovery names a real product and category"
```

---

### Task 3: The Buyer stops burning ~180 s on a failed brief parse

`NebiusBuyerPlanner` uses `ChatOpenAI(timeout=45, max_retries=1)` and `interpret_brief` retries the planner twice, so a failed parse costs `2 x (45 s + 45 s) = 180 s` before the deterministic fallback runs. One attempt with no SDK-level retry bounds the stall at a single timeout, and Task 2's catalog grounding means the fallback is already correct.

The model is the other half of the stall. Measured against the deployed endpoint (`api.tokenfactory.uk-south1.nebius.com`, 3 runs per brief):

| model | median | outcome |
|---|---|---|
| `deepseek-ai/DeepSeek-V4-Pro-0813` | **43.5 s** | 2 of 3 runs fail: `LengthFinishReasonError` — the model burns all 8192 output tokens reasoning and returns a truncated response |
| `openai/gpt-oss-120b` | **2.2 s** | 3 of 3 succeed |

A reasoning model is the wrong tool for a latency-bound structured extraction, so the Buyer gets its own model setting instead of sharing the orchestrator's.

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/planner.py:141-155` (`NebiusBuyerPlanner.__init__`)
- Modify: `apps/buyer_agent/buyer_agent/planner.py:346-354` (`select_buyer_planner`)
- Modify: `apps/buyer_agent/buyer_agent/settings.py` (add `buyer_llm_model` and `buyer_model`)
- Modify: `apps/buyer_agent/buyer_agent/server.py:37-41` and `apps/buyer_agent/buyer_agent/executor.py:55-60` (pass the effective model)
- Modify: `apps/buyer_agent/buyer_agent/graph.py:200-207` (`interpret_brief` retry loop)
- Test: `tests/unit/test_buyer_brief_parsing.py`, `tests/unit/test_llm_providers.py`

**Interfaces:**
- Consumes: `buyer_agent.planner.NebiusBuyerPlanner` (existing).
- Produces:
  - `buyer_agent.settings.Settings.buyer_llm_model: str | None` — env `BUYER_LLM_MODEL`.
  - `buyer_agent.settings.Settings.buyer_model: str` — `buyer_llm_model` or `nebius_model`.
  - `NebiusBuyerPlanner.brief_llm` configured with `max_retries=0` and `request_timeout=45`.

- [x] **Step 1: Write the failing tests**

Append to `tests/unit/test_buyer_brief_parsing.py`:

```python
class FailingPlanner:
    """A brief parser that always fails, to measure the retry budget."""

    def __init__(self) -> None:
        self.calls = 0

    async def parse_brief(self, text, products=None):
        self.calls += 1
        raise TimeoutError("llm timed out")


async def test_interpret_brief_does_not_retry_a_failed_planner() -> None:
    trace = FakeTrace()
    planner = FailingPlanner()
    services = SimpleNamespace(trace=trace, registry=FakeRegistry(CATALOG))
    state = cast(
        BuyerState,
        {"messages": [HumanMessage(content="Negotiate for the MacBook Air.")]},
    )
    config = {
        "configurable": {
            "thread_id": "run-1",
            "services": services,
            "planner": planner,
        }
    }

    result = await interpret_brief(state, config)

    assert planner.calls == 1
    assert result["mandate"]["product_sku"] == "EX-MACBOOK-AIR"


def test_nebius_planner_does_not_retry_inside_the_sdk() -> None:
    from buyer_agent.planner import NebiusBuyerPlanner

    planner = NebiusBuyerPlanner("key", "https://example.invalid/v1", "a-model")

    assert planner.brief_llm.max_retries == 0
    assert planner.brief_llm.request_timeout == 45
```

Append to `tests/unit/test_llm_providers.py`:

```python
def test_buyer_model_prefers_its_own_setting():
    settings = Settings(_env_file=None, buyer_llm_model="openai/gpt-oss-120b")

    assert settings.buyer_model == "openai/gpt-oss-120b"


def test_buyer_model_falls_back_to_the_shared_model():
    settings = Settings(_env_file=None)

    assert settings.buyer_model == settings.nebius_model
```

- [x] **Step 2: Run the tests to verify they fail**

```
.venv/bin/python -m pytest tests/unit/test_buyer_brief_parsing.py -q
```

Expected: `planner.calls == 2` (not 1), and `max_retries` is `1` (not 0).

- [x] **Step 3: Implement**

In `apps/buyer_agent/buyer_agent/planner.py`, in `NebiusBuyerPlanner.__init__`:

```python
        common: dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "temperature": 0,
            # One attempt, no SDK-level retry. The brief parser is not the
            # authority on the product — the catalog is — so a slow or failed
            # model call must not hold the handoff open. The caller falls back
            # to a catalog-grounded mandate instead.
            "timeout": 45,
            "max_retries": 0,
        }
```

In `apps/buyer_agent/buyer_agent/settings.py`, add:

```python
    buyer_llm_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("BUYER_LLM_MODEL"),
    )

    @property
    def buyer_model(self) -> str:
        """The model the Buyer's own planner calls use.

        The Buyer extracts structured facts from a brief and has to answer
        inside the handoff's time budget, so it does not have to share the
        orchestrator's reasoning model.
        """
        return self.buyer_llm_model or self.nebius_model
```

In `apps/buyer_agent/buyer_agent/server.py` and
`apps/buyer_agent/buyer_agent/executor.py`, pass the effective model to
`select_buyer_planner`:

```python
        planner = select_buyer_planner(
            settings.llm_mode,
            settings.nebius_api_key,
            settings.nebius_base_url,
            settings.buyer_model,
        )
```

In `apps/buyer_agent/buyer_agent/graph.py`, in `interpret_brief`:

```python
    mandate = None
    fallback_used = False
    try:
        mandate = await planner.parse_brief(text, products)
        if not isinstance(mandate, Mandate):            mandate = Mandate.model_validate(mandate)
    except Exception:  # noqa: BLE001
        mandate = None
```

- [x] **Step 4: Run the tests to verify they pass**

```
.venv/bin/python -m pytest tests/unit/test_buyer_brief_parsing.py -q
```

Expected: all pass.

- [x] **Step 5: Run the full backend suite**

```
.venv/bin/python -m pytest tests/unit tests/protocol -q
```

Expected: no new failures.

- [x] **Step 6: Commit**

```bash
git add apps/buyer_agent/buyer_agent/planner.py apps/buyer_agent/buyer_agent/graph.py \
  tests/unit/test_buyer_brief_parsing.py
git commit -m "fix(buyer): bound the brief-parse attempt so a failed model call cannot stall the handoff"
```

---

## Track B — Console (`deploy/console`)

### Task 4: Pin the brief format the Buyer parses

The Buyer resolves the product from a `Product SKU: <sku>` line. The orchestrator's instructions said only "a task containing the confirmed mandate plus the grounded product context (SKU, …)", so the model wrote `SKU: EX-MACBOOK-AIR.` and the Buyer dropped the identifier. The instruction now states the exact required line.

**Files:**
- Modify: `apps/console/app/api/copilotkit/[[...slug]]/route.ts:224-232` (orchestrator instructions)
- Test: `apps/console/tests/app/api/copilotkit/route-instructions.test.ts`

**Interfaces:**
- Consumes: the Buyer contract from Task 2 (`Product SKU: <sku>`).
- Produces: no new exports.

- [x] **Step 1: Write the failing test**

Append to `apps/console/tests/app/api/copilotkit/route-instructions.test.ts`:

```ts
  it("pins the Product SKU line the Buyer parses", () => {
    expect(source).toContain("Product SKU:");
    expect(source).toMatch(/MUST\s+include/i);
    expect(source).toMatch(/Product SKU:\s*<sku>/i);
  });
```

- [x] **Step 2: Run the test to verify it fails**

```
cd apps/console && pnpm test tests/app/api/copilotkit/route-instructions.test.ts
```

Expected: FAIL — the source does not contain `Product SKU:`.

- [x] **Step 3: Implement**

In `apps/console/app/api/copilotkit/[[...slug]]/route.ts`, replace the confirmation branch of the instructions:

```
  - If the result is confirmed === true with a complete
    mandate: call send_message_to_a2a_agent with
    agentName="MarketMesh Buyer" and a task containing the
    confirmed mandate plus the grounded product context (SKU,
    name, image_url when known, unit price, offers). Stay in
    the current thread; do not navigate, do not place an order,
    and do not create an award outcome. request_award_approval
    and Verifund HITL approvals remain mandatory. Do not place
    an order.
```

with:

```
  - If the result is confirmed === true with a complete
    mandate: call send_message_to_a2a_agent with
    agentName="MarketMesh Buyer" and a task containing the
    confirmed mandate plus the grounded product context. The
    task MUST include the product identifier on its own line
    in the exact form "Product SKU: <sku>" (for example
    "Product SKU: EX-MACBOOK-AIR"), followed by the product
    name, image_url when known, unit price, and offers. The
    Buyer resolves the product and the sellers to approach
    from that line, so include it whenever a product was
    grounded. Stay in the current thread; do not navigate, do
    not place an order, and do not create an award outcome.
    request_award_approval and Verifund HITL approvals remain
    mandatory. Do not place an order.
```

- [x] **Step 4: Run the test to verify it passes**

```
cd apps/console && pnpm test tests/app/api/copilotkit/route-instructions.test.ts
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add "apps/console/app/api/copilotkit/[[...slug]]/route.ts" \
  apps/console/tests/app/api/copilotkit/route-instructions.test.ts
git commit -m "fix(console): pin the Product SKU line the Buyer parses from the handoff brief"
```

---

### Task 5: Give the handoff route a serverless budget

The Buyer call runs inside the console's AG-UI request. Vercel terminates a function that outlives its budget, so the route declares how long the handoff may take.

**Files:**
- Modify: `apps/console/app/api/copilotkit/[[...slug]]/route.ts:22-23`
- Test: `apps/console/tests/app/api/copilotkit/route-instructions.test.ts`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `export const maxDuration = 300` from the route module.

- [x] **Step 1: Write the failing test**

Append to `apps/console/tests/app/api/copilotkit/route-instructions.test.ts`:

```ts
  it("declares a serverless budget for the handoff route", () => {
    expect(source).toMatch(/export const maxDuration\s*=\s*\d+/);
  });
```

- [x] **Step 2: Run the test to verify it fails**

```
cd apps/console && pnpm test tests/app/api/copilotkit/route-instructions.test.ts
```

Expected: FAIL — no `maxDuration` export.

- [x] **Step 3: Implement**

In `apps/console/app/api/copilotkit/[[...slug]]/route.ts`, next to the existing route exports:

```ts
// Force dynamic rendering for the API route to avoid build-time fetching
export const dynamic = "force-dynamic";
export const revalidate = 0;
// The Buyer handoff runs inside this request. Give the function room for the
// orchestrator's turns and the Buyer's sourcing run instead of letting the
// platform cut the run off mid-negotiation.
export const maxDuration = 300;
```

- [x] **Step 4: Run the test to verify it passes**

```
cd apps/console && pnpm test tests/app/api/copilotkit/route-instructions.test.ts
```

Expected: PASS.

- [x] **Step 5: Run the console suite and typecheck**

```
cd apps/console && pnpm test && pnpm typecheck
```

Expected: the pre-existing failures stay pre-existing and nothing new appears (`product-art-css`, `route-guards`, `example-catalog`; `tests/lib/profile-form-redirect.test.tsx` has a pre-existing TS2556).

- [x] **Step 6: Commit**

```bash
git add "apps/console/app/api/copilotkit/[[...slug]]/route.ts" \
  apps/console/tests/app/api/copilotkit/route-instructions.test.ts
git commit -m "fix(console): declare a serverless budget for the Buyer handoff route"
```

---

## Deploy and verify

- [x] Push `deploy/render` — Render auto-deploys the gateway service.
- [ ] Wait for the deploy, then check `render deploys list srv-dbqvs2ifngtc73eft8b0`.
- [ ] Verify the discovery fix live:
  ```
  curl -sS -X POST https://gateway-795m.onrender.com/registry/v1/discover \
    -H 'Content-Type: application/json' -H 'Authorization: Bearer dev-registry-admin' \
    -d '{"category":"consumer-electronics","required_extension":"https://marketmesh.example/extensions/commerce/v1"}'
  ```
  Expected: one seller (Northwind Audio), not an empty list.
- [x] Push `deploy/console`, then deploy the console with the Vercel CLI from `apps/console`.
- [ ] Drive one handoff end to end in the browser and confirm the Buyer reaches the seller.
- [ ] Confirm the brief-parse latency on the live service from the `buyer` database:
  ```
  psql ... -c "select run_id, created_at, updated_at, stage from runs order by updated_at desc limit 5"
  ```
  Expected: `created_at` and `updated_at` within a few seconds of each other, not minutes apart.

---

## Execution record

The plan above was executed as written for Tasks 1–3 and Track B. Three further
defects were found while verifying against the live deployment and fixed as
scoped additions; they are recorded here rather than folded into the plan text.

### Task 3b — the buyer's counter decision was discarded half the time

`CounterChoice` rejects the whole response when it asks for a change outside
`{warranty_months, split_shipment, shipping_cents, delivery_days}`. The prompt
named those keys as examples of trade-offs but never said the list was
exhaustive, so the model also asked for `returns_days` and `unit_price_cents`.
One unsupported change voided the entire counter: the buyer discarded the
model's decision, fell back to a scripted one, and paid for the model call all
the same.

Fix: state the allowlist in `BUYER_SYSTEM_PROMPT`. Measured over four runs per
model, with the catalog candidates appended:

| model | prompt | median | failures |
|---|---|---|---|
| `deepseek-ai/DeepSeek-V4-Pro-0813` | before | 27.6 s | 1/4 |
| `deepseek-ai/DeepSeek-V4-Pro-0813` | after | 17.5 s | 0/4 |
| `openai/gpt-oss-120b` | before | 2.6 s | 2/4 |
| `openai/gpt-oss-120b` | after | 1.6 s | 0/4 |

Commit `f5088f8` on `deploy/render`.

### Task 3c — the mediation tool crashed every seller call

`agent.py` passed `allowed_card_hosts=` to `mediation.mediate_seller_call()`,
which does not declare that parameter. The call raised `TypeError` before the
mediator started, so every seller call died with `BACKGROUND_EXECUTION_ERROR`
and the run never negotiated.

This was masked until Task 2 made discovery succeed: before the fix the run
died earlier, at discovery. The existing test patched the mediator out with
`**kwargs`, which hid the mismatch; the new test runs the real mediator.

Commit `8014e78` on `deploy/render`.

### Task 3d — the resume landed on the wrong thread

The mediation tool passed the orchestrator's own session id as the buyer's
context id, but the buyer's checkpoint lives on the thread the buyer reports as
its `task_id` (observed live: the buyer's context was `3b36f637…` while the
orchestrator's session was `221093c4…`). Resuming on the orchestrator's thread
finds no buyer state, so the buyer starts a fresh run instead of continuing the
negotiation.

The buyer's contract is "resume on the message's `context_id`" (asserted by
`tests/unit/test_buyer_executor_resume.py`), so the orchestrator was fixed
rather than the buyer.

Commit `5e4c91b` on `deploy/render`.

### Measured result, live

| | before | after |
|---|---|---|
| Buyer brief parse (`interpret_brief`) | 117–191 s | 8.0 s |
| Buyer discovery | 0 sellers — `failed` | 1 seller |
| Seller call | `TypeError`, run aborted | RFQ, counter, offer |
| Negotiation outcome | — | `no_award`: the seller's floor of $1,079.99/unit exceeds the buyer's $400/unit ceiling |

The brief that used to produce `No independently validated sellers were found.`
now reaches the seller in 24.7 s with a bare `SKU:` label and 11.0 s with the
`Product SKU:` label.

### Not changed, and why

- **The orchestrator's model.** Its turns run ~23 s, and tool selection is the
  kind of task a reasoning model is for. The buyer is different: it extracts
  structured facts and has to answer inside the handoff's budget, so it gets
  `BUYER_LLM_MODEL` (default `openai/gpt-oss-120b`).
- **The orchestrator's LLM timeout.** No turn has hung, and a timeout wrong by
  a little would break working behaviour. Worth setting deliberately.
- **The seller's retry budget.** `timeout=30, max_retries=1` is already two
  attempts with a scripted fallback, and the seller's calls are succeeding at
  11–14 s.
