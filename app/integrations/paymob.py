"""Paymob client: Intention API, Unified Checkout URL, HMAC, refunds, inquiry.

Reference: https://developers.paymob.com (Intention API, HMAC transaction callback,
void_refund/refund, transaction inquiry). Amounts are in cents (= piasters for EGP).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.core.errors import IntegrationError

log = logging.getLogger("app.paymob")

TIMEOUT = httpx.Timeout(20.0, connect=10.0)

# Documented concatenation order for the Transaction Processed callback (POST body `obj`).
HMAC_FIELDS: tuple[str, ...] = (
    "amount_cents",
    "created_at",
    "currency",
    "error_occured",
    "has_parent_transaction",
    "id",
    "integration_id",
    "is_3d_secure",
    "is_auth",
    "is_capture",
    "is_refunded",
    "is_standalone_payment",
    "is_voided",
    "order.id",
    "owner",
    "pending",
    "source_data.pan",
    "source_data.sub_type",
    "source_data.type",
    "success",
)


@dataclass(frozen=True, slots=True)
class Intention:
    id: str
    client_secret: str
    paymob_order_id: str | None


@dataclass(frozen=True, slots=True)
class Transaction:
    """The fields we act on, extracted from a callback or an inquiry response."""

    id: str
    success: bool
    pending: bool
    is_refund: bool
    is_voided: bool
    is_refunded: bool
    amount_cents: int
    currency: str
    paymob_order_id: str
    merchant_order_id: str
    raw: dict[str, Any]


def _str(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _dig(data: dict[str, Any], dotted: str) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def hmac_concat(obj: dict[str, Any]) -> str:
    return "".join(_str(_dig(obj, field)) for field in HMAC_FIELDS)


def compute_hmac(obj: dict[str, Any], secret: str) -> str:
    return hmac.new(secret.encode(), hmac_concat(obj).encode(), hashlib.sha512).hexdigest()


def verify_callback(obj: dict[str, Any], received: str | None, secret: str | None = None) -> bool:
    secret = secret if secret is not None else get_settings().paymob_hmac_secret
    if not secret or not received:
        return False
    return hmac.compare_digest(compute_hmac(obj, secret), received.lower())


def parse_transaction(obj: dict[str, Any]) -> Transaction:
    order = obj.get("order")
    if not isinstance(order, dict):  # inquiry responses may inline just the id
        order = {"id": order}
    return Transaction(
        id=_str(obj.get("id")),
        success=bool(obj.get("success")),
        pending=bool(obj.get("pending")),
        is_refund=bool(obj.get("is_refund")),
        is_voided=bool(obj.get("is_voided")),
        is_refunded=bool(obj.get("is_refunded")),
        amount_cents=int(obj.get("amount_cents") or 0),
        currency=_str(obj.get("currency")) or "EGP",
        paymob_order_id=_str(order.get("id")),
        merchant_order_id=_str(order.get("merchant_order_id")),
        raw=obj,
    )


def checkout_url(client_secret: str) -> str:
    s = get_settings()
    query = urlencode({"publicKey": s.paymob_public_key, "clientSecret": client_secret})
    return f"{s.paymob_base_url}/unifiedcheckout/?{query}"


async def _post(path: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    url = f"{get_settings().paymob_base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        log.error("paymob request failed", extra={"ctx": {"path": path, "error": str(exc)}})
        raise IntegrationError("paymob unreachable") from exc
    if response.status_code >= 400:
        # Body never contains secrets; truncate to keep logs small.
        log.error(
            "paymob error",
            extra={
                "ctx": {"path": path, "status": response.status_code, "body": response.text[:500]}
            },
        )
        raise IntegrationError(f"paymob {response.status_code}")
    data: dict[str, Any] = response.json()
    return data


async def create_intention(
    *,
    amount_cents: int,
    special_reference: str,
    billing: dict[str, str],
    items: list[dict[str, Any]],
    extras: dict[str, Any] | None = None,
) -> Intention:
    s = get_settings()
    payload: dict[str, Any] = {
        "amount": amount_cents,
        "currency": "EGP",
        "payment_methods": s.paymob_integration_id_list,
        "items": items,
        "billing_data": billing,
        "special_reference": special_reference,
        "extras": extras or {},
        "notification_url": f"{s.base_url}/webhooks/paymob",
        "redirection_url": f"{s.base_url}/payments/paymob/return",
    }
    data = await _post("/v1/intention/", payload, {"Authorization": f"Token {s.paymob_secret_key}"})
    try:
        return Intention(
            id=str(data["id"]),
            client_secret=str(data["client_secret"]),
            paymob_order_id=str(data["intention_order_id"])
            if data.get("intention_order_id")
            else None,
        )
    except KeyError as exc:
        raise IntegrationError("unexpected paymob intention response") from exc


async def refund(transaction_id: str, amount_cents: int) -> dict[str, Any]:
    s = get_settings()
    return await _post(
        "/api/acceptance/void_refund/refund",
        {"transaction_id": int(transaction_id), "amount_cents": amount_cents},
        {"Authorization": f"Token {s.paymob_secret_key}"},
    )


async def _auth_token() -> str:
    data = await _post("/api/auth/tokens", {"api_key": get_settings().paymob_api_key}, {})
    return str(data["token"])


async def get_transaction(transaction_id: str) -> Transaction | None:
    """Server-to-server status check (needs PAYMOB_API_KEY). None when unavailable."""
    s = get_settings()
    if not s.paymob_api_key or not transaction_id.isdigit():
        return None
    token = await _auth_token()
    url = f"{s.paymob_base_url}/api/acceptance/transactions/{transaction_id}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(url, params={"token": token})
    except httpx.HTTPError as exc:
        raise IntegrationError("paymob unreachable") from exc
    if response.status_code != 200:
        log.warning("paymob inquiry failed", extra={"ctx": {"status": response.status_code}})
        return None
    return parse_transaction(response.json())


async def get_order_transactions(paymob_order_id: str) -> list[Transaction]:
    """All transactions of a Paymob order (needs PAYMOB_API_KEY)."""
    s = get_settings()
    if not s.paymob_api_key or not paymob_order_id:
        return []
    token = await _auth_token()
    url = f"{s.paymob_base_url}/api/ecommerce/orders/{paymob_order_id}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(url, params={"token": token})
    except httpx.HTTPError as exc:
        raise IntegrationError("paymob unreachable") from exc
    if response.status_code != 200:
        return []
    data = response.json()
    txns = data.get("transactions") or []
    return [parse_transaction(t) for t in txns if isinstance(t, dict)]
