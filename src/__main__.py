from __future__ import annotations

import asyncio
import logging
import sys

from src.config import load_config
from src.discord_notifier import DiscordNotifier
from src.ebay_client import EbayClient
from src.scanner import Scanner
from src.store import DealStore


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
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
    discord = DiscordNotifier(config.discord_bot_token)

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
