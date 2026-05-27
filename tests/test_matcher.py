import unittest

from src.gpu_catalog import iter_gpu_definitions
from src.matcher import explain_title_match, matches_title
from src.models import MatchConfig

RTX_3080_BASE = MatchConfig(
    model="3080",
    variant="base",
    family="rtx",
    require_terms=["rtx", "3080"],
    exclude_terms=[],
)

GTX_1080 = MatchConfig(
    model="1080",
    variant="base",
    family="gtx",
    require_terms=["gtx", "1080"],
    exclude_terms=[],
)


class TestMatcher(unittest.TestCase):
    def test_catalog_covers_all_series(self) -> None:
        gpus = iter_gpu_definitions()
        series = {g.series for g in gpus}
        self.assertEqual(series, {10, 20, 30, 40, 50})
        self.assertEqual(len(gpus), 33)

    def test_accepts_valid_3080(self) -> None:
        self.assertTrue(
            matches_title("NVIDIA GeForce RTX 3080 10GB Graphics Card", RTX_3080_BASE)
        )

    def test_accepts_gtx_1080(self) -> None:
        self.assertTrue(
            matches_title("MSI GTX 1080 8GB Gaming Graphics Card", GTX_1080)
        )

    def test_rejects_3050(self) -> None:
        self.assertFalse(
            matches_title("MSI RTX 3050 8GB Graphics Card", RTX_3080_BASE)
        )

    def test_rejects_3080_ti_on_base_search(self) -> None:
        self.assertFalse(
            matches_title("NVIDIA GeForce RTX 3080 Ti 12GB Graphics Card", RTX_3080_BASE)
        )

    def test_rejects_fan_only(self) -> None:
        self.assertFalse(
            matches_title("RTX 3080 Cooling Fan Only", RTX_3080_BASE)
        )

    def test_rejects_cooling_block_only(self) -> None:
        self.assertFalse(
            matches_title("RTX 3080 EK Cooling Block Only", RTX_3080_BASE)
        )

    def test_rejects_parts(self) -> None:
        self.assertFalse(
            matches_title("RTX 3080 10GB for parts spares repair", RTX_3080_BASE)
        )

    def test_rejects_cooling_system_only(self) -> None:
        self.assertFalse(
            matches_title("NVIDIA RTX 4090 Cooling System Only", RTX_3080_BASE)
        )

    def test_rejects_hdmi_port_replacement(self) -> None:
        self.assertFalse(
            matches_title(
                "Replacement HDMI Port for NVIDIA GeForce RTX 3090",
                MatchConfig(
                    model="3090",
                    variant="base",
                    family="rtx",
                    require_terms=["rtx", "3090"],
                ),
            )
        )

    def test_rejects_geforce_in_accessory_title(self) -> None:
        self.assertFalse(
            matches_title(
                "Cooling Fan compatible with GeForce RTX 3080",
                RTX_3080_BASE,
            )
        )

    def test_accepts_watercooled_full_card(self) -> None:
        self.assertTrue(
            matches_title(
                "ASUS ROG Strix RTX 4090 OC 24GB Water Cooled Graphics Card",
                MatchConfig(
                    model="4090",
                    variant="base",
                    family="rtx",
                    require_terms=["rtx", "4090"],
                ),
            )
        )

    def test_rejects_config_banned_word_case_insensitive(self) -> None:
        cfg = MatchConfig(
            model="3080",
            variant="base",
            family="rtx",
            require_terms=["rtx", "3080"],
            exclude_terms=["mycustomban"],
        )
        ok, reason = explain_title_match(
            "NVIDIA RTX 3080 graphics card mycustomBAN", cfg
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "banned_word:mycustomban")


if __name__ == "__main__":
    unittest.main()
