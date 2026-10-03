from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.core.i18n import strip_locale, url
from app.core.security import (
    hash_password,
    order_token,
    verify_order_token,
    verify_password,
)
from app.integrations import paymob
from app.services import shipping_service
from app.utils.money import egp_to_piasters, format_price, percent_off, piasters_to_egp_str
from app.utils.phone import normalize_eg_mobile
from app.utils.text import clean_text, slugify


@pytest.mark.parametrize(
    ("piasters", "locale", "expected"),
    [
        (125000, "en", "1,250 EGP"),
        (125050, "en", "1,250.50 EGP"),
        (5, "en", "0.05 EGP"),
        (125000, "ar", "1,250 ج.م"),
    ],
)
def test_format_price(piasters: int, locale: str, expected: str) -> None:
    assert format_price(piasters, locale) == expected


def test_money_roundtrip() -> None:
    assert egp_to_piasters("799.5") == 79950
    assert egp_to_piasters(100) == 10000
    assert egp_to_piasters("0.015") == 2  # half-up
    assert piasters_to_egp_str(79950) == "799.50"
    assert piasters_to_egp_str(10000) == "100"
    assert percent_off(16000, 20000) == 20
    assert percent_off(20000, None) == 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01012345678", "01012345678"),
        ("0101 234 5678", "01012345678"),
        ("+20 101 234 5678", "01012345678"),
        ("00201212345678", "01212345678"),
        ("٠١٥١٢٣٤٥٦٧٨", "01512345678"),
        ("1012345678", "01012345678"),
        ("01312345678", None),  # 013 is not a mobile prefix
        ("0101234567", None),
        ("hello", None),
    ],
)
def test_normalize_phone(raw: str, expected: str | None) -> None:
    assert normalize_eg_mobile(raw) == expected


def test_shipping_fees() -> None:
    assert shipping_service.fee_for("alexandria") == 5000
    assert shipping_service.fee_for("cairo") == 10000
    rates = shipping_service.all_rates()
    assert len(rates) == 27
    assert shipping_service.lowest_fee() == 5000


def test_paymob_hmac_concatenation_matches_docs() -> None:
    # Worked example from Paymob's HMAC documentation (transaction processed callback).
    obj = {
        "amount_cents": 100,
        "created_at": "2020-03-25T18:39:44.719228",
        "currency": "EGP",
        "error_occured": False,
        "has_parent_transaction": False,
        "id": 2556706,
        "integration_id": 6741,
        "is_3d_secure": True,
        "is_auth": False,
        "is_capture": False,
        "is_refunded": False,
        "is_standalone_payment": True,
        "is_voided": False,
        "order": {"id": 4778239},
        "owner": 4705,
        "pending": False,
        "source_data": {"pan": "2346", "sub_type": "MasterCard", "type": "card"},
        "success": True,
    }
    assert paymob.hmac_concat(obj) == (
        "1002020-03-25T18:39:44.719228EGPfalsefalse25567066741truefalsefalsefalsetrue"
        "false47782394705false2346MasterCardcardtrue"
    )
    good = paymob.compute_hmac(obj, "secret")
    assert paymob.verify_callback(obj, good, "secret")
    assert not paymob.verify_callback(obj, good, "other-secret")
    assert not paymob.verify_callback({**obj, "amount_cents": 1}, good, "secret")
    assert not paymob.verify_callback(obj, None, "secret")


def test_order_token() -> None:
    token = order_token("abc")
    assert verify_order_token("abc", token)
    assert not verify_order_token("abd", token)
    assert not verify_order_token("abc", None)


def test_password_hashing() -> None:
    h = hash_password("correct horse")
    assert verify_password("correct horse", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "not-a-hash")


def test_locale_urls() -> None:
    assert strip_locale("/ar/p/tee") == ("ar", "/p/tee")
    assert strip_locale("/ar") == ("ar", "/")
    assert strip_locale("/arabic") == ("en", "/arabic")
    assert url("/p/tee", "ar") == "/ar/p/tee"
    assert url("/", "ar") == "/ar"
    assert url("/p/tee", "en") == "/p/tee"


def test_text_helpers() -> None:
    assert slugify("Linen Shirt — Sand!") == "linen-shirt-sand"
    assert slugify("قميص") == ""
    assert clean_text("  a \t b\x00 ") == "a b"


def test_locale_catalogs_match() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "backend" / "app" / "locales"
    en = json.loads((root / "en.json").read_text("utf-8"))
    ar = json.loads((root / "ar.json").read_text("utf-8"))
    storefront = {k for k in en if not k.startswith("admin.")}
    assert storefront == set(ar), set(ar) ^ storefront
    placeholders = re.compile(r"\{(\w+)\}")
    for key in ar:
        assert set(placeholders.findall(en[key])) == set(placeholders.findall(ar[key])), key
