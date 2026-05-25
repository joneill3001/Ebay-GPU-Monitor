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
        self._near_miss_threshold = config.near_miss_percentage_threshold
        self._near_misses_channel = config.near_misses_channel

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
        return matches_title(listing.title, search.match, listing.condition)

    def _is_near_miss(
        self, search: SearchConfig, listing: Listing, threshold_pct: float = 7.5
    ) -> bool:
        if not search.match:
            return False
        if not matches_title(listing.title, search.match, listing.condition):
            return False
        over_target = listing.price.landed_cost - search.target_price
        if over_target <= 0:
            return False
        over_pct = (over_target / search.target_price) * 100
        return over_pct <= threshold_pct

    def _matching_target(
        self, group: SearchGroup, listing: Listing
    ) -> SearchConfig | None:
        for target in group.targets:
            if self._is_deal(target, listing):
                return target
        return None

    def _check_near_miss(
        self, group: SearchGroup, listing: Listing, threshold_pct: float = 7.5
    ) -> SearchConfig | None:
        for target in group.targets:
            if self._is_near_miss(target, listing, threshold_pct):
                return target
        return None

    async def _process_group(self, group: SearchGroup) -> tuple[int, int]:
        try:
            listings = await asyncio.to_thread(
                self._ebay.search,
                group.query,
                group.api_max_price,
                label=group.id,
                aspect_filter=group.aspect_filter,
            )
            self._store.increment_api_calls(1)
        except Exception as exc:
            logger.error("eBay search failed for %s: %s", group.id, exc)
            return 0, 0

        deals_found = 0
        with self._store.batch():
            for listing in listings:
                if self._store.has_seen(listing.item_id):
                    logger.debug(
                        "Skipping seen item: %s (%s)",
                        listing.item_id,
                        listing.title[:50],
                    )
                    continue
                if not self._is_newer_than_cursor(group.id, listing):
                    logger.debug(
                        "Skipping old item: %s (%s, age: %.0f min)",
                        listing.item_id,
                        listing.title[:50],
                        self._listing_age_minutes(listing),
                    )
                    continue

                target = self._matching_target(group, listing)
                if target is None:
                    near_miss_target = self._check_near_miss(
                        group, listing, threshold_pct=self._near_miss_threshold
                    )
                    if near_miss_target and self._is_recent_enough(
                        near_miss_target, listing
                    ):
                        if self._near_misses_channel:
                            sent = await self._discord.send_near_miss(
                                near_miss_target,
                                listing,
                                self._near_misses_channel,
                            )
                            if sent:
                                self._store.mark_seen(
                                    listing.item_id,
                                    near_miss_target.id,
                                    commit=False,
                                )
                                logger.info(
                                    "Near miss alert [%s]: %s — £%.2f (target £%.2f, +%.1f%%)",
                                    near_miss_target.id,
                                    listing.title,
                                    listing.price.landed_cost,
                                    near_miss_target.target_price,
                                    (
                                        (listing.price.landed_cost - near_miss_target.target_price)
                                        / near_miss_target.target_price
                                    )
                                    * 100,
                                )
                        else:
                            self._store.add_near_miss(
                                item_id=listing.item_id,
                                search_id=near_miss_target.id,
                                title=listing.title,
                                price=listing.price.landed_cost,
                                target_price=near_miss_target.target_price,
                                url=listing.url,
                                listed_at=listing.listed_at,
                                commit=False,
                            )
                            logger.info(
                                "Near miss [%s]: %s — £%.2f (target £%.2f, +%.1f%%)",
                                near_miss_target.id,
                                listing.title,
                                listing.price.landed_cost,
                                near_miss_target.target_price,
                                (
                                    (listing.price.landed_cost - near_miss_target.target_price)
                                    / near_miss_target.target_price
                                )
                                * 100,
                            )
                    else:
                        logger.debug(
                            "Rejected [%s]: %s — £%.2f (no matching target)",
                            group.id,
                            listing.title[:50],
                            listing.price.landed_cost,
                        )
                    continue

                if not self._is_recent_enough(target, listing):
                    logger.debug(
                        "Rejected [%s]: %s — £%.2f (too old: %.0f min)",
                        target.id,
                        listing.title[:50],
                        listing.price.landed_cost,
                        self._listing_age_minutes(listing),
                    )
                    self._store.mark_seen(listing.item_id, target.id, commit=False)
                    continue

                sent = await self._discord.send_deal(target, listing)
                if sent:
                    self._store.mark_seen(listing.item_id, target.id, commit=False)
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
                self._store.update_cursor(group.id, newest.listed_at, commit=False)

        return len(listings), deals_found

    async def run_cycle(self) -> None:
        removed = self._store.cleanup_old_near_misses()
        if removed:
            logger.debug("Cleaned up %d old near-miss records", removed)

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
