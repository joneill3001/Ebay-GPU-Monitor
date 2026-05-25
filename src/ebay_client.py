from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from src.ebay_filters import GRAPHICS_CARD_CATEGORY_ID, field_filter_fallbacks
from src.pricing import PriceInfo, extract_price
from src.validation import (
    MAX_PRICE_GBP,
    is_safe_ebay_image_url,
    is_safe_ebay_listing_url,
    sanitize_search_query,
    sanitize_title,
)

logger = logging.getLogger(__name__)

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
RATE_LIMITS_URL = "https://api.ebay.com/developer/analytics/v1_beta/rate_limit/"


@dataclass
class Listing:
    item_id: str
    title: str
    url: str
    image_url: str | None
    listed_at: datetime
    price: PriceInfo
    condition: str | None = None


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
        self._delivery_postcode = delivery_postcode
        self._limit = max(1, min(limit, 200))
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._http = httpx.Client(
            timeout=30.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

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

    def _filter_variants(self, target_price: float) -> list[tuple[str, bool]]:
        """Field filter strings from strictest to minimal (eBay 500s on invalid combos)."""
        return field_filter_fallbacks(target_price, self._delivery_postcode)

    def search(
        self,
        query: str,
        max_price: float,
        *,
        label: str = "",
        aspect_filter: str | None = None,
        retries: int = 3,
    ) -> list[Listing]:
        if max_price <= 0 or max_price > MAX_PRICE_GBP:
            raise ValueError(f"max_price must be between 0 and {MAX_PRICE_GBP}")

        safe_query = sanitize_search_query(query)
        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": self._marketplace_id,
            "X-EBAY-C-ENDUSERCTX": self._enduser_ctx(),
        }
        params_base = {
            "q": safe_query,
            "sort": "newlyListed",
            "limit": str(self._limit),
            "category_ids": GRAPHICS_CARD_CATEGORY_ID,
        }
        if aspect_filter:
            params_base["aspect_filter"] = aspect_filter
        log_label = label or query

        last_error: Exception | None = None
        last_body: str = ""
        filter_variants = self._filter_variants(max_price)
        primary_filter = filter_variants[0][0] if filter_variants else ""

        for filter_str, with_conditions in filter_variants:
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
                        last_body = response.text[:200]
                        logger.warning(
                            "eBay HTTP %s for %s (filter len=%d, has_aspect=%s)",
                            response.status_code,
                            log_label,
                            len(filter_str),
                            bool(aspect_filter),
                        )
                        if response.status_code >= 500:
                            break
                        response.raise_for_status()
                    data = response.json()
                    items = data.get("itemSummaries") or []
                    if filter_str != primary_filter:
                        logger.info(
                            "eBay search OK for %s using fallback filter (conditions=%s)",
                            log_label,
                            with_conditions,
                        )
                    return self._parse_items(items)
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
            if not is_safe_ebay_listing_url(url):
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
            if image_url and not is_safe_ebay_image_url(image_url):
                image_url = None

            # Extract condition from eBay API response
            condition = None
            condition_id = item.get("conditionId")
            if condition_id:
                condition = str(condition_id)

            listings.append(
                Listing(
                    item_id=item_id,
                    title=sanitize_title(title),
                    url=url,
                    image_url=image_url,
                    listed_at=listed_at,
                    price=extract_price(item),
                    condition=condition,
                )
            )
        return listings

    def get_rate_limits(self) -> dict[str, Any] | None:
        """Fetch rate limit information from eBay Analytics API."""
        try:
            token = self._get_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            response = self._http.get(RATE_LIMITS_URL, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning("Failed to fetch eBay rate limits: %s", exc)
            return None
