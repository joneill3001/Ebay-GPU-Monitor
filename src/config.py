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
from src.validation import (
    EBAY_MARKETPLACES,
    clamp_float,
    clamp_int,
    is_discord_snowflake,
    normalize_uk_postcode,
    resolve_config_path,
    resolve_data_dir,
)

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
    ebay_api_daily_limit: int = 5000
    near_miss_percentage_threshold: float = 7.5
    near_misses_channel: str | None = None


def _normalize_token(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _resolve_data_dir() -> Path:
    raw = os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))
    return resolve_data_dir(Path(raw), PROJECT_ROOT)


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
        if not is_discord_snowflake(channel_id):
            raise ValueError(
                f"Invalid Discord channel ID for series {group!r}: {channel_id!r}"
            )

        price_value = float(price)
        if price_value <= 0 or price_value > 50_000:
            raise ValueError(
                f"Invalid target price for {gpu.key!r}: {price_value} (must be 0 < price <= 50000)"
            )

        searches.append(
            SearchConfig(
                id=gpu.search_id,
                query=gpu.ebay_query,
                target_price=price_value,
                discord_channel_id=channel_id,
                enabled=True,
                max_listing_age_minutes=default_max_age,
                match=_match_for_gpu(gpu),
            )
        )

    return searches


def load_config() -> AppConfig:
    load_dotenv(PROJECT_ROOT / ".env")

    settings_path = resolve_config_path(
        Path(os.getenv("SETTINGS_PATH", str(CONFIG_DIR / "settings.yaml"))),
        PROJECT_ROOT,
        name="SETTINGS_PATH",
    )
    prices_path = resolve_config_path(
        Path(os.getenv("PRICES_PATH", str(CONFIG_DIR / "prices.yaml"))),
        PROJECT_ROOT,
        name="PRICES_PATH",
    )

    settings = _load_yaml(settings_path)
    prices_raw = _load_yaml(prices_path)

    poll_interval = clamp_int(
        int(
            os.getenv(
                "POLL_INTERVAL_SECONDS",
                settings.get("poll_interval_seconds", 120),
            )
        ),
        name="poll_interval_seconds",
        minimum=30,
        maximum=3600,
    )
    search_limit = clamp_int(
        int(os.getenv("SEARCH_LIMIT", settings.get("limit", 50))),
        name="search_limit",
        minimum=1,
        maximum=200,
    )
    search_delay = clamp_float(
        float(
            os.getenv("SEARCH_DELAY_SECONDS", settings.get("search_delay_seconds", 1.5))
        ),
        name="search_delay_seconds",
        minimum=0.0,
        maximum=60.0,
    )
    api_daily_limit = clamp_int(
        int(
            os.getenv("EBAY_API_DAILY_LIMIT", settings.get("ebay_api_daily_limit", 5000))
        ),
        name="ebay_api_daily_limit",
        minimum=1,
        maximum=1_000_000,
    )
    near_miss_threshold = clamp_float(
        float(
            os.getenv(
                "NEAR_MISS_PERCENTAGE_THRESHOLD",
                settings.get("near_miss_percentage_threshold", 7.5),
            )
        ),
        name="near_miss_percentage_threshold",
        minimum=0.1,
        maximum=50.0,
    )

    searches = _build_searches_from_prices(prices_raw, settings)
    search_groups = build_search_groups(searches)

    near_misses_channel = prices_raw.get("near_misses_channel")
    if near_misses_channel and near_misses_channel != "YOUR_NEAR_MISSES_CHANNEL_ID":
        near_misses_channel = str(near_misses_channel).strip()
        if not is_discord_snowflake(near_misses_channel):
            raise ValueError(
                f"Invalid near_misses_channel in prices.yaml: {near_misses_channel!r}"
            )
    else:
        near_misses_channel = None

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

    marketplace_id = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_GB").strip().upper()
    if marketplace_id not in EBAY_MARKETPLACES:
        raise ValueError(
            f"EBAY_MARKETPLACE_ID must be one of {sorted(EBAY_MARKETPLACES)}, got {marketplace_id!r}"
        )

    postcode_raw = os.getenv("EBAY_DELIVERY_POSTCODE", "").strip()
    delivery_postcode = normalize_uk_postcode(postcode_raw) if postcode_raw else ""

    return AppConfig(
        ebay_client_id=client_id,
        ebay_client_secret=client_secret,
        ebay_marketplace_id=marketplace_id,
        ebay_delivery_postcode=delivery_postcode,
        discord_bot_token=bot_token,
        poll_interval_seconds=poll_interval,
        search_limit=search_limit,
        search_delay_seconds=search_delay,
        config_path=prices_path,
        data_dir=_resolve_data_dir(),
        searches=searches,
        search_groups=search_groups,
        ebay_api_daily_limit=api_daily_limit,
        near_miss_percentage_threshold=near_miss_threshold,
        near_misses_channel=near_misses_channel,
    )
