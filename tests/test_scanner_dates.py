import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from src.ebay_client import Listing
from src.models import MatchConfig, SearchConfig
from src.pricing import PriceInfo
from src.scanner import Scanner


def _listing(age_days: float) -> Listing:
    listed_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    return Listing(
        item_id="v1|336572115433|0",
        title="PALIT NVIDIA GeForce RTX 5070",
        url="https://www.ebay.co.uk/itm/123",
        image_url=None,
        listed_at=listed_at,
        price=PriceInfo(400, 10, 410, "GBP", False),
    )


def _auction_listing(minutes_remaining: int) -> Listing:
    listed_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    end_at = datetime.now(timezone.utc) + timedelta(minutes=minutes_remaining)
    return Listing(
        item_id="v1|336572115434|0",
        title="NVIDIA GeForce RTX 5070 12GB Graphics Card",
        url="https://www.ebay.co.uk/itm/456",
        image_url=None,
        listed_at=listed_at,
        price=PriceInfo(400, 10, 410, "GBP", True),
        end_at=end_at,
    )


class TestScannerDates(unittest.TestCase):
    def test_unseen_within_grace_is_allowed(self) -> None:
        config = MagicMock()
        config.near_miss_percentage_threshold = 10
        config.near_misses_channel = None
        config.relist_grace_minutes = 120
        config.auction_end_soon_minutes = 15

        scanner = Scanner(config, MagicMock(), MagicMock(), MagicMock())
        search = SearchConfig(
            id="rtx-5070",
            query="RTX 5070",
            target_price=500,
            discord_channel_id="1508058247511146647",
            max_listing_age_minutes=45,
            match=MatchConfig(model="5070", family="rtx"),
        )
        listing = _listing(age_days=2 / 24)  # 2 hours
        self.assertTrue(scanner._is_recent_enough(search, listing, unseen=True))

    def test_unseen_far_past_grace_is_rejected(self) -> None:
        config = MagicMock()
        config.near_miss_percentage_threshold = 10
        config.near_misses_channel = None
        config.relist_grace_minutes = 120
        config.auction_end_soon_minutes = 15
        scanner = Scanner(config, MagicMock(), MagicMock(), MagicMock())
        search = SearchConfig(
            id="rtx-5070",
            query="RTX 5070",
            target_price=500,
            discord_channel_id="1508058247511146647",
            max_listing_age_minutes=45,
        )
        listing = _listing(age_days=18.5)
        self.assertFalse(scanner._is_recent_enough(search, listing, unseen=True))

    def test_seen_listing_still_rejected_when_too_old(self) -> None:
        config = MagicMock()
        config.near_miss_percentage_threshold = 10
        config.near_misses_channel = None
        config.relist_grace_minutes = 120
        config.auction_end_soon_minutes = 15
        scanner = Scanner(config, MagicMock(), MagicMock(), MagicMock())
        search = SearchConfig(
            id="rtx-5070",
            query="RTX 5070",
            target_price=500,
            discord_channel_id="1508058247511146647",
            max_listing_age_minutes=45,
        )
        listing = _listing(age_days=18.5)
        self.assertFalse(scanner._is_recent_enough(search, listing, unseen=False))

    def test_auction_ending_soon_is_allowed(self) -> None:
        config = MagicMock()
        config.near_miss_percentage_threshold = 10
        config.near_misses_channel = None
        config.relist_grace_minutes = 120
        config.auction_end_soon_minutes = 15
        scanner = Scanner(config, MagicMock(), MagicMock(), MagicMock())
        self.assertTrue(scanner._is_auction_ending_soon(_auction_listing(10)))

    def test_auction_not_ending_soon_is_blocked(self) -> None:
        config = MagicMock()
        config.near_miss_percentage_threshold = 10
        config.near_misses_channel = None
        config.relist_grace_minutes = 120
        config.auction_end_soon_minutes = 15
        scanner = Scanner(config, MagicMock(), MagicMock(), MagicMock())
        self.assertFalse(scanner._is_auction_ending_soon(_auction_listing(45)))


if __name__ == "__main__":
    unittest.main()
