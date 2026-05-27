from __future__ import annotations

import asyncio
import logging
import os
import sys

from src.config import load_config
from src.discord_notifier import DiscordNotifier
from src.ebay_client import EbayClient
from src.scanner import Scanner
from src.store import DealStore


def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


async def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    try:
        config = load_config()
    except ValueError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    db_path = config.data_dir / "scanner.db"
    store = DealStore(db_path)
    ebay = EbayClient(
        client_id=config.ebay_client_id,
        client_secret=config.ebay_client_secret,
        marketplace_id=config.ebay_marketplace_id,
        delivery_postcode=config.ebay_delivery_postcode,
        limit=config.search_limit,
    )
    discord = DiscordNotifier(
        config.discord_bot_token,
        ebay_client=ebay,
        store=store,
        api_daily_limit=config.ebay_api_daily_limit,
    )

    try:
        await discord.start()
        scanner = Scanner(config, ebay, store, discord)
        await scanner.run_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await discord.close()
        ebay.close()
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
