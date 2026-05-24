import unittest

from src.models import MatchConfig, SearchConfig
from src.search_groups import SearchGroup, build_search_groups


def _search(
    sid: str,
    query: str,
    price: float,
    model: str,
    variant: str = "base",
    family: str = "rtx",
) -> SearchConfig:
    return SearchConfig(
        id=sid,
        query=query,
        target_price=price,
        discord_channel_id="1",
        match=MatchConfig(
            model=model,
            variant=variant,
            family=family,
            require_terms=["rtx", model] if family == "rtx" else ["gtx", model],
        ),
    )


class TestSearchGroups(unittest.TestCase):
    def test_combines_variants_into_one_group(self) -> None:
        searches = [
            _search("rtx-3060", "RTX 3060", 120, "3060", "base"),
            _search("rtx-3060-ti", "RTX 3060 Ti", 150, "3060", "ti"),
        ]
        groups = build_search_groups(searches)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].query, "RTX 3060")
        self.assertEqual(groups[0].api_max_price, 150)
        self.assertEqual(len(groups[0].targets), 2)

    def test_separate_groups_per_model_number(self) -> None:
        searches = [
            _search("rtx-3060", "RTX 3060", 120, "3060"),
            _search("rtx-3070", "RTX 3070", 160, "3070"),
        ]
        groups = build_search_groups(searches)
        self.assertEqual(len(groups), 2)

    def test_full_catalog_group_count(self) -> None:
        from src.config import _build_searches_from_prices

        prices = {
            "channels": {"10": "1", "20": "1", "30": "1", "40": "1", "50": "1"},
            "prices": {gpu.key: 100 for gpu in __import__("src.gpu_catalog", fromlist=["iter_gpu_definitions"]).iter_gpu_definitions()},
        }
        searches = _build_searches_from_prices(prices, {})
        groups = build_search_groups(searches)
        # 3 (10) + 3 (20) + 4 (30) + 4 (40) + 4 (50) = 18 API calls
        self.assertEqual(len(groups), 18)
        self.assertEqual(len(searches), 33)


if __name__ == "__main__":
    unittest.main()
