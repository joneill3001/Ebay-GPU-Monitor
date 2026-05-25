import unittest

from src.ebay_filters import (
    ALLOWED_CONDITION_IDS,
    CHIPSET_ASPECT_NAME,
    build_aspect_filter,
    build_field_filter,
    chipset_aspect_value,
    field_filter_fallbacks,
)
from src.models import MatchConfig, SearchConfig
from src.search_groups import build_search_groups


class TestEbayFilters(unittest.TestCase):
    def test_chipset_aspect_values(self) -> None:
        self.assertEqual(
            chipset_aspect_value("3060", "base", "rtx"),
            "NVIDIA GeForce RTX 3060",
        )
        self.assertEqual(
            chipset_aspect_value("3060", "ti", "rtx"),
            "NVIDIA GeForce RTX 3060 Ti",
        )
        self.assertEqual(
            chipset_aspect_value("2070", "super", "rtx"),
            "NVIDIA GeForce RTX 2070 Super",
        )
        self.assertEqual(
            chipset_aspect_value("1080", "ti", "gtx"),
            "NVIDIA GeForce GTX 1080 Ti",
        )

    def test_aspect_filter_uses_chipset_gpu_model(self) -> None:
        aspect = build_aspect_filter(
            ["NVIDIA GeForce RTX 3060", "NVIDIA GeForce RTX 3060 Ti"]
        )
        self.assertIn(f"categoryId:27386,{CHIPSET_ASPECT_NAME}:", aspect)
        self.assertIn("NVIDIA GeForce RTX 3060 Ti", aspect)
        self.assertNotIn("Chipset:{", aspect)

    def test_field_filter_includes_condition_ids(self) -> None:
        filt = build_field_filter(200.0, delivery_postcode="SW1A1AA")
        self.assertIn("conditionIds:{", filt)
        self.assertIn("deliveryPostalCode:SW1A1AA", filt)
        for cid in ("1000", "3000", "7000"):
            if cid == "7000":
                self.assertNotIn(cid, filt)
            elif cid in ALLOWED_CONDITION_IDS:
                self.assertIn(cid, filt)

    def test_search_group_aspect_includes_all_variants(self) -> None:
        searches = [
            SearchConfig(
                id="rtx-3060",
                query="RTX 3060",
                target_price=120,
                discord_channel_id="1",
                match=MatchConfig(model="3060", variant="base", family="rtx"),
            ),
            SearchConfig(
                id="rtx-3060-ti",
                query="RTX 3060 Ti",
                target_price=150,
                discord_channel_id="1",
                match=MatchConfig(model="3060", variant="ti", family="rtx"),
            ),
        ]
        group = build_search_groups(searches)[0]
        self.assertIn("NVIDIA GeForce RTX 3060 Ti", group.aspect_filter or "")
        self.assertIn("NVIDIA GeForce RTX 3060", group.aspect_filter or "")
        self.assertEqual(group.query, "RTX 3060 graphics card")

    def test_fallbacks_prefer_conditions(self) -> None:
        variants = field_filter_fallbacks(100.0, "SW1A1AA")
        self.assertTrue(variants[0][1])
        self.assertIn("conditionIds:", variants[0][0])


if __name__ == "__main__":
    unittest.main()
