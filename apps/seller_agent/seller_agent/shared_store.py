from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from commerce_core.contracts import Offer, Order
from commerce_core.pricing import SellerCatalogProduct, SellerPolicy
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from seller_agent.mandate import SellerMandate
from seller_agent.store import Reservation, SellerStore, Stock


def canonical_json_bytes(value: Any) -> bytes:
    if isinstance(value, str):
        value = json.loads(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class TenantContextError(RuntimeError):
    """Raised when a store is used without an organization context."""


class ConfigConflict(Exception):
    def __init__(self, current_version: int) -> None:
        super().__init__(
            f"expected_config_version mismatch; current is {current_version}")
        self.current_version = current_version


@dataclass
class ConfigUpsert:
    name: str | None = None
    tagline: str | None = None
    instructions: str | None = None
    max_discount_bps: int | None = None
    autonomy_mode: str | None = None
    tool_allowlist: list[str] | None = None
    expected_config_version: int | None = None


@dataclass
class ConfigSnapshot:
    agent_id: str
    organization_id: str
    seller_id: str
    name: str
    tagline: str
    instructions: str
    max_discount_bps: int
    autonomy_mode: str
    tool_allowlist: list[str]
    policy_version: int
    policy_hash: str
    config_version: int
    status: str


_POLICY_WEIGHTS = ("instructions", "tool_allowlist", "max_discount_bps", "autonomy_mode")


def _snapshot(row) -> ConfigSnapshot:
    return ConfigSnapshot(
        agent_id=row.agent_id, organization_id=row.organization_id,
        seller_id=row.seller_id, name=row.name, tagline=row.tagline or "",
        instructions=row.instructions or "",
        max_discount_bps=row.max_discount_bps, autonomy_mode=row.autonomy_mode,
        tool_allowlist=json.loads(row.tool_allowlist_json or "[]"),
        policy_version=row.policy_version, policy_hash=row.policy_hash,
        config_version=row.config_version, status=row.status,
    )


def _policy_hash(payload: dict[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(payload))


def _jsonable(value: Any) -> Any:
    if isinstance(value, int) and value is not True and value is not False:
        return int(value)
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return value


class OrgScopedTransaction:
    def __init__(self, store: OrgScopedStore, conn) -> None:
        self.store = store
        self.conn = conn

    async def get_offer(self, offer_id: str) -> Offer | None:
        row = (await self.conn.execute(
            text("SELECT offer_json FROM offers "
                 "WHERE organization_id = :o AND offer_id = :i"),
            {"o": self.store.organization_id, "i": offer_id})).first()
        return Offer.model_validate(json.loads(row.offer_json)) if row else None

    async def get_order_by_idempotency(self, key: str) -> Order | None:
        row = (await self.conn.execute(
            text("SELECT order_json FROM orders "
                 "WHERE organization_id = :o AND idempotency_key = :k"),
            {"o": self.store.organization_id, "k": key})).first()
        return Order.model_validate(json.loads(row.order_json)) if row else None

    async def reserve(
        self, sku: str, quantity: int, *, allow_split: bool
    ) -> Reservation:
        row = (await self.conn.execute(
            text("SELECT on_hand, incoming, incoming_days FROM inventory "
                 "WHERE organization_id = :o AND sku = :s"),
            {"o": self.store.organization_id, "s": sku})).first()
        if row is None:
            raise ValueError("unknown sku")
        if row.on_hand >= quantity:
            await self.conn.execute(
                text("UPDATE inventory SET on_hand = on_hand - :q "
                     "WHERE organization_id = :o AND sku = :s"),
                {"q": quantity, "o": self.store.organization_id, "s": sku})
            return Reservation(split_shipment=False)
        if (
            allow_split
            and row.on_hand + row.incoming >= quantity
            and (row.incoming_days is None or row.incoming_days <= 14)
        ):
            remaining = row.on_hand + row.incoming - quantity
            await self.conn.execute(
                text("UPDATE inventory SET on_hand = 0, incoming = :r "
                     "WHERE organization_id = :o AND sku = :s"),
                {"r": remaining, "o": self.store.organization_id, "s": sku})
            return Reservation(split_shipment=True)
        raise ValueError("out_of_stock")

    async def save_order(self, order: Order, *, idempotency_key: str) -> None:
        await self.conn.execute(
            text("""INSERT INTO orders
                        (organization_id, order_id, offer_id, seller_id,
                         idempotency_key, order_json, created_at, agent_id)
                    VALUES (:o, :oid, :fid, :sid, :k, :json, :now, :a)"""),
            {"o": self.store.organization_id, "oid": order.order_id,
             "fid": order.offer_id, "sid": order.seller_id,
             "k": idempotency_key,
             "json": json.dumps(order.model_dump(mode="json")),
             "now": datetime.now(UTC).isoformat(),
             "a": self.store.agent_id})


class OrgScopedStore(SellerStore):
    def __init__(self, engine: AsyncEngine, *, organization_id: str,
                 agent_id: str | None = None) -> None:
        super().__init__(engine)
        org = (organization_id or "").strip()
        if not org:
            raise TenantContextError("organization_id is required")
        self.engine = engine
        self.organization_id = org
        self.agent_id = agent_id

    async def get_config(self, agent_id: str) -> ConfigSnapshot | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                text("SELECT * FROM seller_configs "
                     "WHERE agent_id = :a AND organization_id = :o"),
                {"a": agent_id, "o": self.organization_id},
            )).first()
        return _snapshot(row) if row else None

    async def upsert_config(self, agent_id: str, up: ConfigUpsert, *,
                            seller_id: str, name: str, tagline: str = "") -> ConfigSnapshot:
        current = await self.get_config(agent_id)
        if (up.expected_config_version is not None and current is not None
                and current.config_version != up.expected_config_version):
            raise ConfigConflict(current.config_version)
        if current is None:
            base = ConfigSnapshot(
                agent_id=agent_id, organization_id=self.organization_id,
                seller_id=seller_id, name=name, tagline=tagline,
                instructions="", max_discount_bps=1000, autonomy_mode="policy_bounded",
                tool_allowlist=[], policy_version=1, policy_hash="",
                config_version=0, status="draft",
            )
        else:
            base = current
        merged = ConfigSnapshot(
            agent_id=agent_id, organization_id=self.organization_id,
            seller_id=current.seller_id if current else seller_id,
            name=up.name if up.name is not None else base.name,
            tagline=up.tagline if up.tagline is not None else base.tagline,
            instructions=(up.instructions if up.instructions is not None
                          else base.instructions),
            max_discount_bps=(up.max_discount_bps if up.max_discount_bps is not None
                              else base.max_discount_bps),
            autonomy_mode=(up.autonomy_mode if up.autonomy_mode is not None
                           else base.autonomy_mode),
            tool_allowlist=([str(s) for s in up.tool_allowlist]
                            if up.tool_allowlist is not None else base.tool_allowlist),
            policy_version=base.policy_version, policy_hash=base.policy_hash,
            config_version=base.config_version + 1, status=base.status,
        )
        policy_payload = {
            "instructions": merged.instructions,
            "tool_allowlist": sorted(merged.tool_allowlist),
            "max_discount_bps": merged.max_discount_bps,
            "autonomy_mode": merged.autonomy_mode,
        }
        new_hash = _policy_hash(policy_payload)
        policy_changed = new_hash != (current.policy_hash if current else "")
        if policy_changed and current is not None:
            merged.policy_version = base.policy_version + 1
        merged.policy_hash = new_hash
        async with self.engine.begin() as conn:
            if current:
                await conn.execute(text(
                    """UPDATE seller_configs
                       SET name=:name, tagline=:tagline, instructions=:ins,
                           max_discount_bps=:m, autonomy_mode=:mode,
                           tool_allowlist_json=:al, policy_version=:pv,
                           policy_hash=:ph, config_version=:cv, updated_at=:now
                       WHERE agent_id=:a AND organization_id=:o"""
                ), {"name": merged.name, "tagline": merged.tagline,
                    "ins": merged.instructions, "m": merged.max_discount_bps,
                    "mode": merged.autonomy_mode,
                    "al": json.dumps(merged.tool_allowlist),
                    "pv": merged.policy_version, "ph": merged.policy_hash,
                    "cv": merged.config_version, "a": agent_id,
                    "o": self.organization_id,
                    "now": datetime.now(UTC).isoformat()})
            else:
                await conn.execute(text(
                    """INSERT INTO seller_configs
                       (agent_id, organization_id, seller_id, name, tagline,
                        instructions, max_discount_bps, autonomy_mode,
                        tool_allowlist_json, policy_version, policy_hash, config_version)
                       VALUES (:a, :o, :sid, :name, :tag, :ins, :m, :mode, :al,
                               :pv, :ph, :cv)"""
                ), {"a": agent_id, "o": self.organization_id, "sid": seller_id,
                    "name": merged.name, "tag": merged.tagline,
                    "ins": merged.instructions, "m": merged.max_discount_bps,
                    "mode": merged.autonomy_mode,
                    "al": json.dumps(merged.tool_allowlist),
                    "pv": merged.policy_version, "ph": merged.policy_hash,
                    "cv": merged.config_version})
        return merged

    async def list_products(self) -> list[dict]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(
                text("SELECT * FROM products WHERE organization_id = :o"),
                {"o": self.organization_id},
            )).all()
        return [dict(row._mapping) for row in rows]

    async def import_products(self, products: list[dict], *, replace: bool) -> dict:
        counts = {"inserted": 0, "updated": 0, "replaced": 0}
        async with self.engine.begin() as conn:
            if replace:
                skus = [p["sku"] for p in products]
                if skus:
                    placeholder = ", ".join(f":s{i}" for i in range(len(skus)))
                    params = {f"s{i}": s for i, s in enumerate(skus)} | {
                        "o": self.organization_id}
                    result = await conn.execute(
                        text(f"DELETE FROM products WHERE organization_id = :o "
                             f"AND sku NOT IN ({placeholder})"),
                        params)
                    counts["replaced"] = getattr(result, "rowcount", 0) or 0
                    await conn.execute(text(
                        "DELETE FROM inventory WHERE organization_id = :o "
                        "AND sku NOT IN (SELECT sku FROM products "
                        "WHERE organization_id = :o)"),
                        {"o": self.organization_id})
                else:
                    await conn.execute(text(
                        "DELETE FROM products WHERE organization_id = :o"),
                        {"o": self.organization_id})
                    await conn.execute(text(
                        "DELETE FROM inventory WHERE organization_id = :o"),
                        {"o": self.organization_id})
            for p in products:
                existing = (await conn.execute(
                    text("SELECT sku FROM products "
                         "WHERE organization_id = :o AND sku = :s"),
                    {"o": self.organization_id, "s": p["sku"]},
                )).first()
                cols: dict[str, Any] = {
                    "organization_id": self.organization_id,
                    "sku": p["sku"],
                    "name": p.get("name") or "Unnamed",
                    "category": p.get("category") or "general",
                    "description": p.get("description") or "",
                    "list_unit_price_cents": p["list_unit_price_cents"],
                    "original_unit_price_cents": p.get("original_unit_price_cents"),
                    "initial_unit_price_cents": p["initial_unit_price_cents"],
                    "floor_unit_price_cents": p["floor_unit_price_cents"],
                    "concession_ladder_json": json.dumps(
                        p.get("concession_ladder_cents") or []),
                    "warranty_addons_json": json.dumps(
                        _jsonable(p.get("warranty_addons_cents") or {})),
                    "base_warranty_months": p.get("base_warranty_months", 12),
                    "returns_days": p.get("returns_days", 30),
                    "delivery_days": p.get("delivery_days", 5),
                    "stock_on_hand": p.get("stock_on_hand", 0),
                    "incoming_stock": p.get("incoming_stock", 0),
                    "incoming_days": p.get("incoming_days"),
                    "image_emoji": p.get("image_emoji") or "📦",
                    "color": p.get("color") or "#eef2ed",
                    "rating": p.get("rating"),
                    "reviews": p.get("reviews") or "",
                    "tag": p.get("tag") or "",
                    "color_name": p.get("color_name") or "black",
                    "sustainability_certified": (
                        None if p.get("sustainability_certified") is None
                        else (1 if p["sustainability_certified"] else 0)),
                }
                insert_cols = ", ".join(cols)
                insert_vals = ", ".join(f":{k}" for k in cols)
                update_cols = ", ".join(
                    f"{k}=:{k}" for k in cols if k not in ("sku", "organization_id"))
                await conn.execute(text(
                    f"INSERT INTO products ({insert_cols}) VALUES ({insert_vals}) "
                    f"ON CONFLICT(organization_id, sku) DO UPDATE SET {update_cols},"
                    f" updated_at = datetime('now')"
                ), cols)
                await conn.execute(text(
                    """INSERT INTO inventory (organization_id, sku, on_hand,
                                            incoming, incoming_days)
                       VALUES (:o, :sku, :oh, :inc, :ind)
                       ON CONFLICT(organization_id, sku) DO UPDATE SET
                         on_hand=:oh, incoming=:inc, incoming_days=:ind"""
                ), {"o": self.organization_id, "sku": p["sku"],
                    "oh": p.get("stock_on_hand", 0),
                    "inc": p.get("incoming_stock", 0),
                    "ind": p.get("incoming_days")})
                if existing:
                    counts["updated"] += 1
                else:
                    counts["inserted"] += 1
        return counts

    async def first_sku(self) -> str | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                text("SELECT sku FROM products WHERE organization_id = :o "
                     "ORDER BY sku LIMIT 1"),
                {"o": self.organization_id})).first()
        return row[0] if row else None

    async def find_stock(self, sku: str) -> dict | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                text("SELECT on_hand, incoming, incoming_days FROM inventory "
                     "WHERE organization_id = :o AND sku = :s"),
                {"o": self.organization_id, "s": sku})).first()
        return dict(row._mapping) if row else None

    async def load_policy(self) -> SellerPolicy:
        if not self.agent_id:
            raise TenantContextError("load_policy requires a bound agent")
        products = await self.list_products()
        snapshot = await self.get_config(self.agent_id)
        if snapshot is None:
            raise TenantContextError("seller config not found for agent")
        first = products[0] if products else {}
        catalog = [
            SellerCatalogProduct(
                sku=p["sku"], name=p["name"],
                category=p.get("category") or "general",
                description=p.get("description") or "",
                list_unit_price_cents=p["list_unit_price_cents"],
                original_unit_price_cents=p.get("original_unit_price_cents"),
                floor_unit_price_cents=p["floor_unit_price_cents"],
                initial_unit_price_cents=p["initial_unit_price_cents"],
                concession_ladder_cents=json.loads(p.get("concession_ladder_json") or "[]"),
                base_warranty_months=p.get("base_warranty_months"),
                warranty_addons_cents={int(k): v for k, v in json.loads(
                    p.get("warranty_addons_json") or "{}").items()},
                returns_days=p.get("returns_days"),
                delivery_days=p.get("delivery_days"),
                stock_on_hand=p.get("stock_on_hand"),
                incoming_stock=p.get("incoming_stock"),
                incoming_days=p.get("incoming_days"),
                image_emoji=p.get("image_emoji") or "📦",
                color=p.get("color") or "#eef2ed",
                rating=p.get("rating"),
                reviews=p.get("reviews") or "",
                tag=p.get("tag") or "",
                color_name=p.get("color_name") or "black",
                sustainability_certified=(
                    None if p.get("sustainability_certified") is None
                    else bool(p["sustainability_certified"])),
            )
            for p in products
        ]
        defaults = {
            "list_unit_price_cents": first.get("list_unit_price_cents") or 1,
            "floor_unit_price_cents": first.get("floor_unit_price_cents") or 1,
            "initial_unit_price_cents": first.get("initial_unit_price_cents") or 1,
            "concession_ladder_cents": json.loads(first.get("concession_ladder_json") or "[]"),
            "base_warranty_months": first.get("base_warranty_months") or 0,
            "warranty_addons_cents": {int(k): v for k, v in json.loads(
                first.get("warranty_addons_json") or "{}").items()},
            "returns_days": first.get("returns_days") or 0,
            "delivery_days": first.get("delivery_days") or 1,
            "stock_on_hand": first.get("stock_on_hand") or 0,
            "incoming_stock": first.get("incoming_stock") or 0,
            "incoming_days": first.get("incoming_days"),
            "sustainability_certified": bool(first.get("sustainability_certified") or False),
            "rating": first.get("rating") or 4.5,
        }
        return SellerPolicy(
            seller_id=snapshot.seller_id,
            name=snapshot.name,
            tagline=snapshot.tagline,
            categories=sorted({(p.get("category") or "general") for p in products})
            or ["general"],
            sku=(first.get("sku") or "unknown"),
            product_name=(first.get("name") or "Product"),
            product_description=(first.get("description") or ""),
            image_emoji=(first.get("image_emoji") or "📦"),
            product_tag=(first.get("tag") or ""),
            product_color=(first.get("color") or "#eef2ed"),
            color=(first.get("color_name") or "black"),
            list_unit_price_cents=defaults["list_unit_price_cents"],
            floor_unit_price_cents=defaults["floor_unit_price_cents"],
            initial_unit_price_cents=defaults["initial_unit_price_cents"],
            concession_ladder_cents=defaults["concession_ladder_cents"],
            base_warranty_months=defaults["base_warranty_months"],
            warranty_addons_cents=defaults["warranty_addons_cents"],
            returns_days=defaults["returns_days"],
            delivery_days=defaults["delivery_days"],
            stock_on_hand=defaults["stock_on_hand"],
            incoming_stock=defaults["incoming_stock"],
            incoming_days=defaults["incoming_days"],
            sustainability_certified=defaults["sustainability_certified"],
            rating=defaults["rating"],
            products=catalog,
            mandate=None,
        )

    async def get_stock(self, sku: str) -> Stock:
        async with self.engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT on_hand, incoming, incoming_days FROM inventory "
                "WHERE organization_id = :o AND sku = :s"),
                {"o": self.organization_id, "s": sku})).first()
            if row is not None:
                return Stock(on_hand=int(row.on_hand),
                             incoming=int(row.incoming),
                             incoming_days=row.incoming_days)
            product = (await conn.execute(text(
                "SELECT stock_on_hand FROM products "
                "WHERE organization_id = :o AND sku = :s"),
                {"o": self.organization_id, "s": sku})).first()
        if product is None:
            return Stock(0, 0, None)
        return Stock(on_hand=int(product.stock_on_hand or 0), incoming=0)

    async def save_offer(self, offer: Offer, *, task_id: str,
                         context_id: str) -> None:
        payload = offer.model_dump(mode="json")
        created = datetime.now(UTC).isoformat()
        async with self.engine.begin() as conn:
            await conn.execute(text(
                """INSERT INTO offers
                       (organization_id, offer_id, task_id, context_id, seller_id,
                        offer_json, created_at)
                   VALUES (:o, :oid, :tid, :cid, :sid, :json, :now)
                   ON CONFLICT(organization_id, offer_id) DO UPDATE SET
                       offer_json=excluded.offer_json"""
            ), {"o": self.organization_id, "oid": offer.offer_id,
                "tid": task_id, "cid": context_id,
                "sid": offer.seller_id, "json": json.dumps(payload),
                "now": created})

    async def get_offer(self, offer_id: str):
        async with self.engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT offer_json FROM offers "
                "WHERE organization_id = :o AND offer_id = :oid"),
                {"o": self.organization_id, "oid": offer_id})).first()
        if row is None:
            return None
        return Offer.model_validate(json.loads(row.offer_json))

    async def get_latest_offer(self, task_id: str):
        async with self.engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT offer_json FROM offers "
                "WHERE organization_id = :o AND task_id = :tid"
                " ORDER BY created_at DESC LIMIT 1"),
                {"o": self.organization_id, "tid": task_id})).first()
        if row is None:
            return None
        return Offer.model_validate(json.loads(row.offer_json))

    async def load_mandate(self) -> SellerMandate:
        return SellerMandate()

    async def record_task_ownership(self, task_id: str,
                                    context_id: str | None = None) -> None:
        if not self.agent_id:
            raise TenantContextError("task ownership requires a bound agent")
        async with self.engine.begin() as conn:
            await conn.execute(text(
                """INSERT OR IGNORE INTO task_ownership
                       (task_id, organization_id, agent_id, context_id)
                   VALUES (:t, :o, :a, :c)"""
            ), {"t": task_id, "o": self.organization_id,
                "a": self.agent_id, "c": context_id})

    async def create_schema(self) -> None:
        return None

    async def seed_catalog(self, policy: SellerPolicy) -> None:
        return None

    @asynccontextmanager
    async def transaction(self):
        async with self.engine.begin() as conn:
            yield OrgScopedTransaction(self, conn)

    async def set_stock(
        self,
        sku: str,
        on_hand: int,
        incoming: int = 0,
        incoming_days: int | None = None,
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text(
                """INSERT INTO inventory
                       (organization_id, sku, on_hand, incoming, incoming_days)
                   VALUES (:o, :s, :oh, :inc, :ind)
                   ON CONFLICT(organization_id, sku) DO UPDATE SET
                     on_hand = :oh, incoming = :inc, incoming_days = :ind"""
            ), {"o": self.organization_id, "s": sku, "oh": int(on_hand),
                "inc": int(incoming), "ind": incoming_days})

    async def list_offers(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT offer_json, created_at FROM offers "
                "WHERE organization_id = :o ORDER BY created_at DESC LIMIT :n"),
                {"o": self.organization_id,
                 "n": max(1, min(limit, 100))})).all()
        return [{
            "created_at": row.created_at,
            "offer": Offer.model_validate(
                json.loads(row.offer_json)).model_dump(mode="json"),
        } for row in rows]

    async def list_orders(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT order_json, created_at FROM orders "
                "WHERE organization_id = :o ORDER BY created_at DESC LIMIT :n"),
                {"o": self.organization_id,
                 "n": max(1, min(limit, 100))})).all()
        return [{
            "created_at": row.created_at,
            "order": Order.model_validate(
                json.loads(row.order_json)).model_dump(mode="json"),
        } for row in rows]

    async def save_order(
        self, order: Order, *, idempotency_key: str
    ) -> None:
        async with self.transaction() as tx:
            await tx.save_order(order, idempotency_key=idempotency_key)

    async def get_order_by_idempotency(self, idempotency_key: str) -> Order | None:
        async with self.transaction() as tx:
            return await tx.get_order_by_idempotency(idempotency_key)

    async def reserve(
        self, sku: str, quantity: int, *, allow_split: bool
    ) -> dict[str, Any]:
        async with self.transaction() as tx:
            reservation = await tx.reserve(
                sku, quantity, allow_split=allow_split)
        stock = await self.get_stock(sku)
        return {"split_shipment": reservation.split_shipment,
                "on_hand": stock.on_hand}

    async def save_settlement_token(
        self, transaction_id: str, seller_id: str, token: str
    ) -> None:
        now = datetime.now(UTC).isoformat()
        async with self.engine.begin() as conn:
            await conn.execute(text(
                """INSERT INTO settlement_tokens
                       (organization_id, transaction_id, seller_id,
                        token_json, created_at, updated_at)
                   VALUES (:o, :t, :s, :j, :now, :now)
                   ON CONFLICT(organization_id, transaction_id) DO UPDATE SET
                     token_json = :j, seller_id = :s, updated_at = :now"""
            ), {"o": self.organization_id, "t": transaction_id,
                "s": seller_id, "j": json.dumps({"token": token}),
                "now": now})

    async def save_settlement_context(
        self, *, transaction_id: str, seller_id: str
    ) -> None:
        """Record a known settlement without persisting a secret."""
        now = datetime.now(UTC).isoformat()
        async with self.engine.begin() as conn:
            await conn.execute(text(
                """INSERT INTO settlement_tokens
                       (organization_id, transaction_id, seller_id,
                        token_json, created_at, updated_at)
                   VALUES (:o, :t, :s, :j, :now, :now)
                   ON CONFLICT(organization_id, transaction_id) DO UPDATE SET
                     seller_id = :s, updated_at = :now"""
            ), {"o": self.organization_id, "t": transaction_id,
                "s": seller_id, "j": json.dumps({"token": ""}),
                "now": now})

    async def get_settlement_token(self, transaction_id: str) -> str | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT token_json FROM settlement_tokens "
                "WHERE organization_id = :o AND transaction_id = :t"),
                {"o": self.organization_id, "t": transaction_id})).first()
        return json.loads(row.token_json)["token"] if row else None

    async def list_settlement_tokens(
        self, limit: int = 5
    ) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT transaction_id, seller_id, updated_at "
                "FROM settlement_tokens WHERE organization_id = :o "
                "ORDER BY updated_at DESC LIMIT :n"),
                {"o": self.organization_id,
                 "n": max(1, min(limit, 20))})).all()
        return [dict(row._mapping) for row in rows]

    async def enqueue_evidence(
        self,
        *,
        transaction_id: str,
        seller_id: str,
        kind: str | None = None,
        requirement_id: str | None = None,
        content: bytes,
        media_type: str,
        filename: str,
        note: str = "",
        captured_at: str | None = None,
        created_at: datetime | None = None,
    ) -> bool:
        resolved = requirement_id or kind
        if not resolved:
            raise ValueError("requirement_id is required")
        now = (created_at or datetime.now(UTC)).isoformat()
        async with self.engine.begin() as conn:
            result = await conn.execute(text(
                """INSERT INTO evidence_outbox
                       (organization_id, outbox_id, transaction_id, seller_id,
                        kind, requirement_id, filename, media_type, content, note, captured_at,
                        next_attempt_at, created_at, agent_id)
                   VALUES (:o, :id, :t, :s, :k, :k, :f, :m, :c, :n, :cap,
                           :now, :now, :a)
                   ON CONFLICT(organization_id, transaction_id, kind)
                   DO NOTHING"""
            ), {"o": self.organization_id, "id": uuid.uuid4().hex,
                "t": transaction_id, "s": seller_id, "k": resolved,
                "f": filename, "m": media_type, "c": content, "n": note,
                "cap": captured_at, "now": now, "a": self.agent_id})
        return bool(result.rowcount)

    async def list_due_evidence(
        self, *, now: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT * FROM evidence_outbox WHERE organization_id = :o "
                "AND status = 'pending' AND next_attempt_at <= :now "
                "ORDER BY created_at LIMIT :n"),
                {"o": self.organization_id, "now": now,
                 "n": max(1, min(limit, 100))})).all()
        return [dict(row._mapping) | {"evidence_key": row.outbox_id}
                for row in rows]

    async def mark_evidence_sent(
        self, evidence_key: str, *, sent_at: str
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text(
                "UPDATE evidence_outbox SET status = 'sent', sent_at = :s, "
                "last_error = NULL WHERE organization_id = :o "
                "AND outbox_id = :id"),
                {"s": sent_at, "o": self.organization_id, "id": evidence_key})

    async def reschedule_evidence(
        self, evidence_key: str, *, next_attempt_at: str, error: str
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text(
                "UPDATE evidence_outbox SET attempts = attempts + 1, "
                "next_attempt_at = :n, last_error = :e "
                "WHERE organization_id = :o AND outbox_id = :id"),
                {"n": next_attempt_at, "e": error,
                 "o": self.organization_id, "id": evidence_key})

    async def fail_evidence(self, evidence_key: str, *, error: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text(
                "UPDATE evidence_outbox SET status = 'failed', "
                "attempts = attempts + 1, last_error = :e "
                "WHERE organization_id = :o AND outbox_id = :id"),
                {"e": error, "o": self.organization_id, "id": evidence_key})

    async def get_evidence_outbox(
        self, transaction_id: str, kind: str
    ) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT * FROM evidence_outbox WHERE organization_id = :o "
                "AND transaction_id = :t AND kind = :k"),
                {"o": self.organization_id, "t": transaction_id,
                 "k": kind})).first()
        if row is None:
            return None
        return dict(row._mapping) | {"evidence_key": row.outbox_id}
