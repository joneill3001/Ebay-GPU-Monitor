from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from src.config import AppConfig
from src.models import SearchConfig
from src.discord_notifier import DiscordNotifier
from src.ebay_client import EbayClient, Listing
from src.matcher import explain_title_match
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
        self._relist_grace_minutes = config.relist_grace_minutes
        self._log_item_decisions = config.log_item_decisions
        self._auction_end_soon_minutes = max(
            1, int(getattr(config, "auction_end_soon_minutes", 15))
        )

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

    def _listing_age_minutes(self, listing: Listing) -> float:
        listed = listing.listed_at
        if listed.tzinfo is None:
            listed = listed.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - listed).total_seconds() / 60.0

    def _is_recent_enough(
        self,
        search: SearchConfig,
        listing: Listing,
        *,
        unseen: bool = False,
    ) -> bool:
        age = self._listing_age_minutes(listing)
        limit = search.max_listing_age_minutes
        if age <= limit:
            return True
        grace_limit = limit + self._relist_grace_minutes
        if unseen and self._relist_grace_minutes > 0 and age <= grace_limit:
            logger.info(
                "Unseen listing slightly past age limit (%.0f min, grace to %d min): %s",
                age,
                grace_limit,
                listing.item_id,
            )
            return True
        return False

    def _deal_decision(self, search: SearchConfig, listing: Listing) -> tuple[bool, str]:
        if listing.price.is_auction and not self._is_auction_ending_soon(listing):
            return False, "auction_not_ending_soon"
        if listing.price.landed_cost > search.target_price:
            return False, "price_above_target"
        if not search.match:
            return False, "no_match_config"
        return explain_title_match(listing.title, search.match, listing.condition)

    def _is_near_miss(
        self, search: SearchConfig, listing: Listing, threshold_pct: float = 7.5
    ) -> bool:
        if listing.price.is_auction and not self._is_auction_ending_soon(listing):
            return False
        if not search.match:
            return False
        title_ok, _ = explain_title_match(listing.title, search.match, listing.condition)
        if not title_ok:
            return False
        over_target = listing.price.landed_cost - search.target_price
        if over_target <= 0:
            return False
        over_pct = (over_target / search.target_price) * 100
        return over_pct <= threshold_pct

    def _is_auction_ending_soon(self, listing: Listing) -> bool:
        if not listing.price.is_auction:
            return True
        if listing.end_at is None:
            return False
        end_at = listing.end_at
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        remaining_minutes = (end_at - now).total_seconds() / 60.0
        if remaining_minutes <= 0:
            return False
        return remaining_minutes <= self._auction_end_soon_minutes

    def _matching_target(
        self, group: SearchGroup, listing: Listing
    ) -> tuple[SearchConfig | None, list[str]]:
        reasons: list[str] = []
        for target in group.targets:
            ok, reason = self._deal_decision(target, listing)
            if ok:
                return target, reasons
            reasons.append(f"{target.id}:{reason}")
        return None, reasons

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
        seen_ids = self._store.filter_seen_ids([listing.item_id for listing in listings])
        seen_count = 0
        new_count = 0
        consecutive_seen = 0
        with self._store.batch():
            for listing in listings:
                if listing.item_id in seen_ids:
                    seen_count += 1
                    consecutive_seen += 1
                    if self._log_item_decisions:
                        logger.debug(
                            "Skipped [%s]: %s — £%.2f (already_seen)",
                            group.id,
                            listing.title[:80],
                            listing.price.landed_cost,
                        )
                    # Results are newlyListed — a long run of seen IDs means the rest
                    # of the page is almost certainly stale too.
                    if consecutive_seen >= 10:
                        break
                    continue

                consecutive_seen = 0
                new_count += 1
                if self._log_item_decisions:
                    logger.info(
                        "New [%s]: %s — £%.2f",
                        group.id,
                        listing.title[:90],
                        listing.price.landed_cost,
                    )

                marked = False
                should_retry_notification = False

                target, deal_reasons = self._matching_target(group, listing)
                if target is not None:
                    if self._is_recent_enough(target, listing, unseen=True):
                        sent = await self._discord.send_deal(target, listing)
                        if sent:
                            self._store.mark_seen(
                                listing.item_id, target.id, commit=False
                            )
                            marked = True
                            deals_found += 1
                            logger.info(
                                "Deal alert [%s]: %s — £%.2f (target £%.2f)",
                                target.id,
                                listing.title,
                                listing.price.landed_cost,
                                target.target_price,
                            )
                        else:
                            logger.warning(
                                "Rejected [%s]: %s — £%.2f (notify_failed:deal_send)",
                                target.id,
                                listing.title[:80],
                                listing.price.landed_cost,
                            )
                            should_retry_notification = True
                    else:
                        logger.info(
                            "Rejected [%s]: %s — £%.2f (too old: %.0f min)",
                            target.id,
                            listing.title[:50],
                            listing.price.landed_cost,
                            self._listing_age_minutes(listing),
                        )
                else:
                    near_miss_target = self._check_near_miss(
                        group, listing, threshold_pct=self._near_miss_threshold
                    )
                    if near_miss_target and self._is_recent_enough(
                        near_miss_target, listing, unseen=True
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
                                marked = True
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
                                logger.warning(
                                    "Rejected [%s]: %s — £%.2f (notify_failed:near_miss_send)",
                                    near_miss_target.id,
                                    listing.title[:80],
                                    listing.price.landed_cost,
                                )
                                should_retry_notification = True
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
                            self._store.mark_seen(
                                listing.item_id, near_miss_target.id, commit=False
                            )
                            marked = True
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
                        reason_text = ", ".join(deal_reasons[:4]) if deal_reasons else "no_matching_target"
                        logger.info(
                            "Rejected [%s]: %s — £%.2f (%s)",
                            group.id,
                            listing.title[:80],
                            listing.price.landed_cost,
                            reason_text,
                        )

                if not marked:
                    if should_retry_notification:
                        # Keep unseen when an eligible notification failed to deliver.
                        continue
                    self._store.mark_seen(listing.item_id, group.id, commit=False)

        if self._log_item_decisions and listings:
            logger.info(
                "Group summary [%s]: fetched=%d seen=%d new=%d deals=%d",
                group.id,
                len(listings),
                seen_count,
                new_count,
                deals_found,
            )

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
