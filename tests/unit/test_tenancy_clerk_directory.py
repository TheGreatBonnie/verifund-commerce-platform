from __future__ import annotations

from clerk_backend_api import models
from verifund_control_plane.tenancy.clerk import ClerkBackendDirectory


class FakeOrganizationMembershipsSDK:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeSDK:
    def __init__(self, response):
        self.organization_memberships = FakeOrganizationMembershipsSDK(response)


async def test_membership_uses_organization_memberships_resource():
    response = models.OrganizationMemberships.model_construct(
        data=[
            models.OrganizationMembership.model_construct(
                id="mem_1", role="org:admin"
            )
        ],
        total_count=1,
    )
    directory = ClerkBackendDirectory("sk_test")
    directory._sdk = FakeSDK(response)

    membership = await directory.membership("org_1", "user_1")

    assert membership == {
        "id": "mem_1",
        "organization": {"id": "org_1"},
        "public_user_data": {"user_id": "user_1"},
        "role": "org:admin",
    }
    assert directory._sdk.organization_memberships.calls == [
        {"organization_id": "org_1", "user_id": ["user_1"]}
    ]


async def test_membership_returns_none_when_no_membership_exists():
    response = models.OrganizationMemberships.model_construct(data=[], total_count=0)
    directory = ClerkBackendDirectory("sk_test")
    directory._sdk = FakeSDK(response)

    assert await directory.membership("org_1", "user_1") is None
