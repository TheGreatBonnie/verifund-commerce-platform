import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Request
from verifund_control_plane.app import create_app
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.settings import Settings
from verifund_control_plane.tenancy.identity import _default_authenticator


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def seeded_identity(client):
    app = client._transport.app
    store = app.state.tenancy
    user = await store.upsert_user("user_1", "a@example.com", "A")
    org = await store.upsert_organization("org_1", "Acme", "acme")
    await store.upsert_membership(org["id"], user["id"], "org:admin", "mem_1")
    return {"tenant_id": org["id"]}


async def test_require_identity_rejects_missing_token(client):
    # No authenticator installed: Clerk verification with empty keys fails closed
    # so the route does not return identity without a token.
    response = await client.get("/v1/me")
    assert response.status_code in (401, 403, 500)


async def test_require_identity_expands_role_from_database(client, seeded_identity):
    app = client._transport.app
    app.state.clerk_authenticator = lambda request: {
        "sub": "user_1",
        "org_id": "org_1",
        "org_role": "org:admin",
    }
    response = await client.get("/v1/me", headers={"authorization": "Bearer x"})
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == seeded_identity["tenant_id"]
    assert "org:transactions:read" in body["permissions"]


@pytest.fixture
def clerk_keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _session_token(private_pem: str, azp: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "user_1",
            "azp": azp,
            "iat": now,
            "exp": now + 600,
            "iss": "https://test.clerk.accounts.dev",
            "v": 1,
        },
        private_pem,
        algorithm="RS256",
    )


def _auth_settings(public_pem: str, tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="https://tunnel.example.dev",
        console_base_url="http://127.0.0.1:3000",
        clerk_secret_key="sk_test_dummy",
        clerk_jwt_key=public_pem,
    )


def _auth_request(token: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/seller/onboarding",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
    )


def test_default_authenticator_accepts_token_from_public_origin(clerk_keys, tmp_path):
    """Regression: tokens issued for the public console origin must verify.

    The console is demoed through a tunnel, so Clerk sets the session token
    azp to the public base URL, not the loopback console base URL.
    """
    private_pem, public_pem = clerk_keys
    settings = _auth_settings(public_pem, tmp_path)
    token = _session_token(private_pem, azp=settings.public_base_url)
    payload = _default_authenticator(_auth_request(token), settings)
    assert payload["sub"] == "user_1"


def test_default_authenticator_accepts_token_from_console_origin(clerk_keys, tmp_path):
    """Control case: the loopback console origin keeps working."""
    private_pem, public_pem = clerk_keys
    settings = _auth_settings(public_pem, tmp_path)
    token = _session_token(private_pem, azp=settings.console_base_url)
    payload = _default_authenticator(_auth_request(token), settings)
    assert payload["sub"] == "user_1"


def test_default_authenticator_rejects_token_from_unknown_origin(clerk_keys, tmp_path):
    """Guard: widening authorized_parties must not accept arbitrary origins."""
    private_pem, public_pem = clerk_keys
    settings = _auth_settings(public_pem, tmp_path)
    token = _session_token(private_pem, azp="https://evil.example.com")
    with pytest.raises(VerifundError) as exc_info:
        _default_authenticator(_auth_request(token), settings)
    assert exc_info.value.status_code == 401
