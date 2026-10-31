import json
from datetime import datetime, timezone

from verifund_control_plane.agreements.digest import (
    agreement_hash, canonical_json, sha256_hex,
)


def test_canonical_json_sorted_compact():
    assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_agreement_hash_binds_version():
    terms = {"schema": "verifund.agreement.v1", "agreement_type": "goods",
             "terms_version": 1, "totals": {"total_cents": 100}}
    h1 = agreement_hash("agr_1", 1, terms)
    h2 = agreement_hash("agr_1", 2, terms)
    assert h1 != h2
    assert len(h1) == 64


def test_tamper_detection():
    terms = {"schema": "verifund.agreement.v1", "agreement_type": "goods",
             "terms_version": 1, "totals": {"total_cents": 100}}
    h = agreement_hash("agr_1", 1, terms)
    terms["totals"]["total_cents"] = 200
    assert agreement_hash("agr_1", 1, terms) != h
