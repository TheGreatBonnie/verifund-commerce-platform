from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from commerce_core.pricing import SellerPolicy, SellerCatalogProduct
from commerce_core.contracts import Offer
from seller_agent.mandate import SellerMandate
from seller_agent.store import Stock


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


class OrgScopedStore:
    def __init__(self, engine: AsyncEngine, *, organization_id: str,
                 agent_id: str | None = None) -> None:
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
                        f"AND sku NOT IN (SELECT sku FROM products "
                        f"WHERE organization_id = :o)"),
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
            **defaults,
            products=catalog,
            mandate=None,
        )

    async def get_stock(self, sku: str) -> Stock:
        async with self.engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT p.stock_on_hand AS ph, i.on_hand AS oh, "
                "       i.incoming AS inc, i.incoming_days AS ind "
                "FROM products p LEFT JOIN inventory i "
                "  ON i.organization_id = p.organization_id AND i.sku = p.sku "
                "WHERE p.organization_id = :o AND p.sku = :s"),
                {"o": self.organization_id, "s": sku})).first()
        if row is None:
            return Stock(0, 0, None)
        on_hand = row.oh if row.oh is not None else (row.ph or 0)
        incoming = row.inc if row.inc is not None else 0
        return Stock(on_hand=int(on_hand), incoming=int(incoming),
                     incoming_days=row.ind)

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
