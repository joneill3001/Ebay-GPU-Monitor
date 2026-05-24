from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from src.pricing import PriceInfo, extract_price

logger = logging.getLogger(__name__)

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


@dataclass
class Listing:
    item_id: str
    title: str
    url: str
    image_url: str | None
    listed_at: datetime
    price: PriceInfo
    raw: dict[str, Any]


class EbayClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        marketplace_id: str,
        delivery_postcode: str,
        limit: int = 50,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._marketplace_id = marketplace_id
        self._delivery_postcode = delivery_postcode.replace(" ", "").upper()
        self._limit = limit
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._http = httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._http.close()

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        response = self._http.post(
            OAUTH_URL,
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            auth=(self._client_id, self._client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 7200))
        self._token_expires_at = time.time() + expires_in
        return self._token

    def _enduser_ctx(self) -> str:
        if self._delivery_postcode:
            return (
                f"contextualLocation=country%3DGB%2Czip%3D"
                f"{quote(self._delivery_postcode, safe='')}"
            )
        return "contextualLocation=country%3DGB"

    def _filter_variants(self, target_price: float) -> list[str]:
        """Filter sets from most specific to minimal (eBay 500s on invalid combos)."""
        max_price = int(target_price)
        base = [
            f"deliveryCountry:GB,price:[..{max_price}],priceCurrency:GBP",
        ]
        with_postcode = (
            f"deliveryCountry:GB,deliveryPostalCode:{self._delivery_postcode},"
            f"price:[..{max_price}],priceCurrency:GBP"
            if self._delivery_postcode
            else None
        )

        # buyingOptions + newlyListed is unsupported (eBay error 12034) — omit buyingOptions.
        # Default results are mostly Buy It Now; auction/BIN combo listings are still included.
        variants = []
        if with_postcode:
            variants.append(with_postcode)
        variants.append(base[0])
        variants.append(f"deliveryCountry:GB,price:[..{max_price}]")
        return variants

    def search(
        self,
        query: str,
        max_price: float,
        *,
        label: str = "",
        retries: int = 3,
    ) -> list[Listing]:
        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": self._marketplace_id,
            "X-EBAY-C-ENDUSERCTX": self._enduser_ctx(),
        }
        params_base = {
            "q": query,
            "sort": "newlyListed",
            "limit": str(self._limit),
        }
        log_label = label or query

        last_error: Exception | None = None
        last_body: str = ""
        filter_variants = self._filter_variants(max_price)

        for filter_str in filter_variants:
            params = {**params_base, "filter": filter_str}
            for attempt in range(retries):
                try:
                    response = self._http.get(
                        SEARCH_URL, params=params, headers=headers
                    )
                    if response.status_code == 429:
                        wait = 2**attempt
                        logger.warning("eBay rate limited, retrying in %ss", wait)
                        time.sleep(wait)
                        continue
                    if response.status_code >= 400:
                        last_body = response.text[:500]
                        logger.warning(
                            "eBay HTTP %s (filter=%s): %s",
                            response.status_code,
                            filter_str,
                            last_body,
                        )
                        if response.status_code >= 500:
                            break
                        response.raise_for_status()
                    data = response.json()
                    if filter_str != filter_variants[0]:
                        logger.info(
                            "eBay search OK for %s using simplified filter",
                            log_label,
                        )
                    return self._parse_items(data.get("itemSummaries") or [])
                except httpx.HTTPError as exc:
                    last_error = exc
                    wait = 2**attempt
                    logger.warning("eBay request failed (%s), retry in %ss", exc, wait)
                    time.sleep(wait)

        if last_error:
            raise RuntimeError(
                f"eBay search failed for '{log_label}' after trying all filter variants. "
                f"Last response: {last_body or last_error}"
            ) from last_error
        return []

    def _parse_items(self, items: list[dict[str, Any]]) -> list[Listing]:
        listings: list[Listing] = []
        for item in items:
            item_id = item.get("itemId")
            title = item.get("title")
            url = item.get("itemWebUrl")
            if not item_id or not title or not url:
                continue

            listed_raw = item.get("itemOriginDate")
            if listed_raw:
                listed_at = datetime.fromisoformat(
                    listed_raw.replace("Z", "+00:00")
                )
            else:
                listed_at = datetime.now(timezone.utc)

            image = item.get("image") or {}
            image_url = image.get("imageUrl")

            listings.append(
                Listing(
                    item_id=item_id,
                    title=title,
                    url=url,
                    image_url=image_url,
                    listed_at=listed_at,
                    price=extract_price(item),
                    raw=item,
                )
            )
        return listings
