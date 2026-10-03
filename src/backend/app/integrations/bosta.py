"""Bosta courier client: create a delivery for an order.

Based on Bosta's public SDKs (POST {base}/deliveries, `Authorization: <api key>`).
Verify the payload against Bosta's current API docs once the business has its
API key: city names and optional fields may differ per account.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import IntegrationError

log = logging.getLogger("app.bosta")

TYPE_SEND = 10  # Package delivery (forward)


@dataclass(frozen=True, slots=True)
class Delivery:
    id: str
    tracking_number: str


def tracking_url(tracking_number: str) -> str:
    return f"https://bosta.co/tracking-shipments?shipment-number={tracking_number}"


async def create_delivery(
    *,
    reference: str,
    cod_piasters: int,
    first_name: str,
    last_name: str,
    phone: str,
    email: str | None,
    city: str,
    address: str,
    items_count: int,
    description: str,
    notes: str | None,
) -> Delivery:
    s = get_settings()
    payload: dict[str, Any] = {
        "type": TYPE_SEND,
        "specs": {"packageDetails": {"itemsCount": items_count, "description": description[:200]}},
        "cod": round(cod_piasters / 100, 2),
        "dropOffAddress": {"city": city, "firstLine": address[:250]},
        "receiver": {"firstName": first_name, "lastName": last_name or first_name, "phone": phone},
        "businessReference": reference,
    }
    if email:
        payload["receiver"]["email"] = email
    if notes:
        payload["notes"] = notes[:250]
    if s.bosta_pickup_location_id:
        payload["businessLocationId"] = s.bosta_pickup_location_id

    url = f"{s.bosta_base_url.rstrip('/')}/deliveries"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            response = await client.post(
                url, json=payload, headers={"Authorization": s.bosta_api_key}
            )
    except httpx.HTTPError as exc:
        raise IntegrationError("bosta unreachable") from exc
    body: dict[str, Any] = response.json() if response.content else {}
    if response.status_code >= 400 or body.get("success") is False:
        log.error(
            "bosta error",
            extra={"ctx": {"status": response.status_code, "body": str(body)[:500]}},
        )
        raise IntegrationError(str(body.get("message") or f"bosta {response.status_code}"))
    data = body.get("data") or body
    try:
        return Delivery(id=str(data["_id"]), tracking_number=str(data["trackingNumber"]))
    except KeyError as exc:
        raise IntegrationError("unexpected bosta response") from exc
