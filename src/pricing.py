from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PriceInfo:
    item_price: float
    shipping_cost: float
    landed_cost: float
    currency: str
    is_auction: bool


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _item_price(item: dict[str, Any]) -> tuple[float, str, bool]:
    buying = item.get("buyingOptions") or []
    is_auction = "AUCTION" in buying

    price_obj = item.get("currentBidPrice") if is_auction else item.get("price")
    if not price_obj:
        price_obj = item.get("price")

    value = _parse_float(price_obj.get("value") if price_obj else None)
    currency = str(price_obj.get("currency", "GBP") if price_obj else "GBP")
    if value is None:
        return 0.0, currency, is_auction
    return value, currency, is_auction


def _shipping_cost(item: dict[str, Any]) -> float:
    options = item.get("shippingOptions") or []
    costs: list[float] = []

    for option in options:
        cost_obj = option.get("shippingCost")
        if not cost_obj:
            continue
        value = _parse_float(cost_obj.get("value"))
        if value is not None:
            costs.append(value)

    if not costs:
        return 0.0
    return min(costs)


def extract_price(item: dict[str, Any]) -> PriceInfo:
    item_price, currency, is_auction = _item_price(item)
    shipping = _shipping_cost(item)
    landed = item_price + shipping
    return PriceInfo(
        item_price=item_price,
        shipping_cost=shipping,
        landed_cost=landed,
        currency=currency,
        is_auction=is_auction,
    )
