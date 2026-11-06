import pytest

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.tenancy.visibility import assert_resource_visible


def test_buyer_cannot_read_seller_payout_account():
    with pytest.raises(VerifundError) as exc:
        assert_resource_visible("buyer", "payout_account")
    assert exc.value.status_code == 403


def test_buyer_can_read_agreement():
    assert_resource_visible("buyer", "agreement")
