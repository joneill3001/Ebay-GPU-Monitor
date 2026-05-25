import unittest
from pathlib import Path

from src.validation import (
    is_discord_snowflake,
    is_safe_ebay_image_url,
    is_safe_ebay_listing_url,
    normalize_uk_postcode,
    resolve_config_path,
    sanitize_title,
)


class TestValidation(unittest.TestCase):
    def test_discord_snowflake(self) -> None:
        self.assertTrue(is_discord_snowflake("1508058247511146647"))
        self.assertFalse(is_discord_snowflake("not-a-channel"))
        self.assertFalse(is_discord_snowflake("123"))

    def test_uk_postcode(self) -> None:
        self.assertEqual(normalize_uk_postcode("sw1a 1aa"), "SW1A1AA")

    def test_postcode_rejects_injection(self) -> None:
        with self.assertRaises(ValueError):
            normalize_uk_postcode("SW1A;DROP")

    def test_ebay_urls(self) -> None:
        self.assertTrue(
            is_safe_ebay_listing_url("https://www.ebay.co.uk/itm/123456789")
        )
        self.assertFalse(is_safe_ebay_listing_url("https://evil.example/phish"))

    def test_ebay_image_urls(self) -> None:
        self.assertTrue(
            is_safe_ebay_image_url("https://i.ebayimg.com/images/g/abc/s-l500.jpg")
        )
        self.assertFalse(is_safe_ebay_image_url("https://evil.example/x.jpg"))

    def test_config_path_traversal_blocked(self) -> None:
        root = Path(__file__).resolve().parent.parent
        outside = (root.parent / "outside.yaml").resolve()
        with self.assertRaises(ValueError):
            resolve_config_path(outside, root, name="SETTINGS_PATH")

    def test_title_truncation(self) -> None:
        long_title = "x" * 1000
        self.assertEqual(len(sanitize_title(long_title)), 512)


if __name__ == "__main__":
    unittest.main()
