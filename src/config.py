from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.gpu_catalog import (
    GpuDefinition,
    channel_group_for_series,
    iter_gpu_definitions,
)
from src.models import MatchConfig, SearchConfig
from src.search_groups import SearchGroup, build_search_groups

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

DEFAULT_EXCLUDE_TERMS: list[str] = []


@dataclass
class AppConfig:
    ebay_client_id: str
    ebay_client_secret: str
    ebay_marketplace_id: str
    ebay_delivery_postcode: str
    discord_bot_token: str
    poll_interval_seconds: int
    search_limit: int
    search_delay_seconds: float
    config_path: Path
    data_dir: Path
    searches: list[SearchConfig]
    search_groups: list[SearchGroup] = field(default_factory=list)


def _normalize_token(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _resolve_data_dir() -> Path:
    data_dir = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    return data_dir


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _match_for_gpu(gpu: GpuDefinition) -> MatchConfig:
    if gpu.family == "gtx":
        require = ["gtx", gpu.model]
    else:
        require = ["rtx", gpu.model]
    return MatchConfig(
        model=gpu.model,
        variant=gpu.variant,
        family=gpu.family,
        require_terms=require,
        exclude_terms=list(DEFAULT_EXCLUDE_TERMS),
    )


def _build_searches_from_prices(
    prices_raw: dict[str, Any],
    settings: dict[str, Any],
) -> list[SearchConfig]:
    if not settings.get("enabled", True):
        return []

    channels = prices_raw.get("channels") or {}
    prices = prices_raw.get("prices") or {}
    default_max_age = int(
        settings.get("max_listing_age_minutes", 45)
    )

    searches: list[SearchConfig] = []
    for gpu in iter_gpu_definitions():
        price = prices.get(gpu.key)
        if price is None:
            continue

        group = channel_group_for_series(gpu.series)
        channel_id = str(channels.get(group, "")).strip()
        if not channel_id or channel_id == "YOUR_CHANNEL_ID":
            continue

        searches.append(
            SearchConfig(
                id=gpu.search_id,
                query=gpu.ebay_query,
                target_price=float(price),
                discord_channel_id=channel_id,
                enabled=True,
                max_listing_age_minutes=default_max_age,
                match=_match_for_gpu(gpu),
            )
        )

    return searches


def load_config() -> AppConfig:
    load_dotenv(PROJECT_ROOT / ".env")

    settings_path = Path(
        os.getenv("SETTINGS_PATH", str(CONFIG_DIR / "settings.yaml"))
    )
    prices_path = Path(os.getenv("PRICES_PATH", str(CONFIG_DIR / "prices.yaml")))
    if not settings_path.is_absolute():
        settings_path = PROJECT_ROOT / settings_path
    if not prices_path.is_absolute():
        prices_path = PROJECT_ROOT / prices_path

    settings = _load_yaml(settings_path)
    prices_raw = _load_yaml(prices_path)

    poll_interval = int(
        os.getenv(
            "POLL_INTERVAL_SECONDS",
            settings.get("poll_interval_seconds", 120),
        )
    )
    search_limit = int(os.getenv("SEARCH_LIMIT", settings.get("limit", 50)))
    search_delay = float(
        os.getenv("SEARCH_DELAY_SECONDS", settings.get("search_delay_seconds", 1.5))
    )

    searches = _build_searches_from_prices(prices_raw, settings)
    search_groups = build_search_groups(searches)

    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
    bot_token = _normalize_token(os.getenv("DISCORD_BOT_TOKEN", ""))

    if not client_id or not client_secret:
        raise ValueError("EBAY_CLIENT_ID and EBAY_CLIENT_SECRET must be set in .env")
    if not bot_token or bot_token in {"your_discord_bot_token", "YOUR_DISCORD_BOT_TOKEN"}:
        raise ValueError(
            "DISCORD_BOT_TOKEN must be set in .env — use Bot → Reset Token "
            "from the Discord Developer Portal"
        )
    if "." not in bot_token:
        raise ValueError("DISCORD_BOT_TOKEN does not look valid")
    if not searches:
        raise ValueError(
            "No searches loaded. Check config/prices.yaml has channel IDs and a price "
            "for each GPU key you want to scan."
        )

    return AppConfig(
        ebay_client_id=client_id,
        ebay_client_secret=client_secret,
        ebay_marketplace_id=os.getenv("EBAY_MARKETPLACE_ID", "EBAY_GB"),
        ebay_delivery_postcode=os.getenv("EBAY_DELIVERY_POSTCODE", "").strip(),
        discord_bot_token=bot_token,
        poll_interval_seconds=poll_interval,
        search_limit=search_limit,
        search_delay_seconds=search_delay,
        config_path=prices_path,
        data_dir=_resolve_data_dir(),
        searches=searches,
        search_groups=search_groups,
    )
