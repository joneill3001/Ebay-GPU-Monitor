from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from src.config import AppConfig
from src.models import SearchConfig
from src.discord_notifier import DiscordNotifier
from src.ebay_client import EbayClient, Listing
from src.matcher import matches_title
from src.search_groups import SearchGroup
from src.store import DealStore

logger = logging.getLogger(__name__)


class Scanner:
    def __init__(
        self,
        config: AppConfig,
        ebay: EbayClient,
        store: DealStore,
        discord: DiscordNotifier,
    ) -> None:
        self._config = config
        self._ebay = ebay
        self._store = store
        self._discord = discord

    async def verify_channels(self) -> None:
        seen: set[str] = set()
        for search in self._config.searches:
            if search.discord_channel_id in seen:
                continue
            seen.add(search.discord_channel_id)
            ok = await self._discord.verify_channel(search.discord_channel_id)
            if ok:
                logger.info("Discord channel OK (%s)", search.discord_channel_id)
            else:
                logger.warning(
                    "Discord channel %s not accessible",
                    search.discord_channel_id,
                )

    def _is_newer_than_cursor(self, group_id: str, listing: Listing) -> bool:
        cursor = self._store.get_cursor(group_id)
        if cursor is None:
            return True
        listed = listing.listed_at
        if listed.tzinfo is None:
            listed = listed.replace(tzinfo=timezone.utc)
        cursor_aware = cursor if cursor.tzinfo else cursor.replace(tzinfo=timezone.utc)
        return listed > cursor_aware

    def _listing_age_minutes(self, listing: Listing) -> float:
        listed = listing.listed_at
        if listed.tzinfo is None:
            listed = listed.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - listed).total_seconds() / 60.0

    def _is_recent_enough(self, search: SearchConfig, listing: Listing) -> bool:
        return self._listing_age_minutes(listing) <= search.max_listing_age_minutes

    def _is_deal(self, search: SearchConfig, listing: Listing) -> bool:
        if listing.price.landed_cost > search.target_price:
            return False
        if not search.match:
            return False
        return matches_title(listing.title, search.match)

    def _matching_target(
        self, group: SearchGroup, listing: Listing
    ) -> SearchConfig | None:
        for target in group.targets:
            if self._is_deal(target, listing):
                return target
        return None

    async def _process_group(self, group: SearchGroup) -> tuple[int, int]:
        try:
            listings = self._ebay.search(
                group.query,
                group.api_max_price,
                label=group.id,
            )
        except Exception as exc:
            logger.error("eBay search failed for %s: %s", group.id, exc)
            return 0, 0

        deals_found = 0
        for listing in listings:
            if self._store.has_seen(listing.item_id):
                continue
            if not self._is_newer_than_cursor(group.id, listing):
                continue

            target = self._matching_target(group, listing)
            if target is None:
                continue

            if not self._is_recent_enough(target, listing):
                self._store.mark_seen(listing.item_id, target.id)
                continue

            sent = await self._discord.send_deal(target, listing)
            if sent:
                self._store.mark_seen(listing.item_id, target.id)
                deals_found += 1
                logger.info(
                    "Deal alert [%s]: %s — £%.2f (target £%.2f)",
                    target.id,
                    listing.title,
                    listing.price.landed_cost,
                    target.target_price,
                )

        if listings:
            newest = max(listings, key=lambda x: x.listed_at)
            self._store.update_cursor(group.id, newest.listed_at)

        return len(listings), deals_found

    async def run_cycle(self) -> None:
        total_items = 0
        total_deals = 0
        groups = self._config.search_groups
        delay = self._config.search_delay_seconds

        for i, group in enumerate(groups):
            items, deals = await self._process_group(group)
            total_items += items
            total_deals += deals
            logger.info(
                "Cycle %s (%s): fetched=%d deals=%d",
                group.id,
                group.target_labels,
                items,
                deals,
            )
            if delay > 0 and i < len(groups) - 1:
                await asyncio.sleep(delay)

        logger.info("Cycle complete: items=%d deals=%d", total_items, total_deals)

    async def run_forever(self) -> None:
        await self.verify_channels()
        n_groups = len(self._config.search_groups)
        n_targets = len(self._config.searches)
        logger.info(
            "Scanner started — %d eBay calls/cycle (%d GPU targets), poll every %ds",
            n_groups,
            n_targets,
            self._config.poll_interval_seconds,
        )
        while True:
            cycle_start = time.monotonic()
            await self.run_cycle()
            elapsed = time.monotonic() - cycle_start
            sleep_for = max(0.0, self._config.poll_interval_seconds - elapsed)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
