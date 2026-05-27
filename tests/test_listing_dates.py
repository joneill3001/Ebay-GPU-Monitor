import unittest
from datetime import datetime, timezone

from src.listing_dates import parse_age_at, parse_listed_at


class TestListingDates(unittest.TestCase):
    def test_age_at_prefers_creation_date(self) -> None:
        item = {
            "itemOriginDate": "2026-05-01T10:00:00.000Z",
            "itemCreationDate": "2026-05-20T14:30:00.000Z",
        }
        self.assertEqual(
            parse_age_at(item),
            datetime(2026, 5, 20, 14, 30, tzinfo=timezone.utc),
        )

    def test_listed_at_uses_latest(self) -> None:
        item = {
            "itemOriginDate": "2026-05-01T10:00:00.000Z",
            "itemCreationDate": "2026-05-20T14:30:00.000Z",
        }
        self.assertEqual(
            parse_listed_at(item),
            datetime(2026, 5, 20, 14, 30, tzinfo=timezone.utc),
        )

    def test_age_at_falls_back_to_origin(self) -> None:
        item = {"itemOriginDate": "2026-05-10T08:00:00.000Z"}
        self.assertEqual(
            parse_age_at(item),
            datetime(2026, 5, 10, 8, 0, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
