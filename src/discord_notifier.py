from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from src.models import SearchConfig
from src.ebay_client import Listing
from src.validation import is_discord_snowflake, is_safe_ebay_image_url, is_safe_ebay_listing_url

if TYPE_CHECKING:
    from src.ebay_client import EbayClient
    from src.store import DealStore

logger = logging.getLogger(__name__)

API_USAGE_COOLDOWN_SECONDS = 30


def _listed_ago(listed_at: datetime) -> str:
    if listed_at.tzinfo is None:
        listed_at = listed_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    seconds = int((now - listed_at).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''} ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def _embed_color(deal_pct: float) -> int:
    if deal_pct >= 25:
        return 0x1ABC9C
    if deal_pct >= 15:
        return 0x2ECC71
    if deal_pct >= 5:
        return 0x27AE60
    return 0x58D68D


def _load_owner_role_ids() -> frozenset[str]:
    raw = os.getenv("DISCORD_OWNER_ROLE_IDS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _member_has_owner_access(member: discord.Member, allowed_role_ids: frozenset[str]) -> bool:
    if allowed_role_ids:
        member_role_ids = {str(role.id) for role in member.roles}
        return bool(member_role_ids & allowed_role_ids)

    for role in member.roles:
        cleaned = "".join(role.name.split()).lower()
        if "owner" in cleaned:
            return True
    return False


def build_deal_embed(search: SearchConfig, listing: Listing) -> discord.Embed:
    target = search.target_price
    price = listing.price.landed_cost
    below = target - price
    deal_pct = round((below / target) * 100, 1) if target > 0 else 0.0

    price_label = "Current bid (incl. shipping)" if listing.price.is_auction else "Price (incl. shipping)"

    embed = discord.Embed(
        title=listing.title[:256],
        url=listing.url,
        color=_embed_color(deal_pct),
        description=f"**{deal_pct}%** below target · **£{below:.2f}** under £{target:.2f}",
    )
    embed.add_field(name=price_label, value=f"£{price:.2f}", inline=True)
    embed.add_field(name="Target", value=f"£{target:.2f}", inline=True)
    embed.add_field(name="Listed", value=_listed_ago(listing.listed_at), inline=True)

    if listing.price.shipping_cost > 0:
        embed.add_field(
            name="Breakdown",
            value=(
                f"Item: £{listing.price.item_price:.2f} · "
                f"Shipping: £{listing.price.shipping_cost:.2f}"
            ),
            inline=False,
        )

    if listing.image_url:
        embed.set_thumbnail(url=listing.image_url)

    embed.set_footer(text=f"{search.id} · {listing.item_id}")
    return embed


class DiscordNotifier:
    def __init__(
        self,
        token: str,
        ebay_client: EbayClient | None = None,
        store: DealStore | None = None,
        api_daily_limit: int = 5000,
    ) -> None:
        intents = discord.Intents.default()
        self._client = discord.Client(intents=intents)
        self._token = token
        self._ready = asyncio.Event()
        self._channels: dict[str, discord.abc.Messageable] = {}
        self._runner: asyncio.Task[None] | None = None
        self._ebay_client = ebay_client
        self._store = store
        self._api_daily_limit = api_daily_limit
        self._owner_role_ids = _load_owner_role_ids()
        self._api_usage_last_call: dict[int, float] = {}
        self._tree = app_commands.CommandTree(self._client)

        @self._client.event
        async def on_ready() -> None:
            logger.info("Discord bot connected as %s", self._client.user)
            self._ready.set()
            try:
                await self._tree.sync()
                logger.info("Slash commands synced")
            except Exception as exc:
                logger.warning("Failed to sync slash commands: %s", exc)

        self._tree.command(name="api_usage", description="Check eBay API usage")(
            self._api_usage_slash
        )

    async def start(self) -> None:
        self._runner = asyncio.create_task(self._client.start(self._token))

        try:
            await asyncio.wait_for(self._ready.wait(), timeout=30.0)
        except asyncio.TimeoutError as exc:
            if self._runner and not self._runner.done():
                self._runner.cancel()
            login_error = None
            if self._runner:
                try:
                    await self._runner
                except discord.LoginFailure as err:
                    login_error = err
            if login_error:
                raise RuntimeError(
                    "Invalid DISCORD_BOT_TOKEN in .env. "
                    "Use Bot → Reset Token in the Discord Developer Portal "
                    "(not the Application ID or Client Secret). "
                    "No quotes around the token."
                ) from login_error
            raise RuntimeError("Discord bot failed to connect within 30 seconds") from exc

    async def close(self) -> None:
        await self._client.close()
        if self._runner and not self._runner.done():
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass

    async def verify_channel(self, channel_id: str) -> bool:
        channel = await self._resolve_channel(channel_id)
        return channel is not None

    async def _resolve_channel(self, channel_id: str) -> discord.abc.Messageable | None:
        if not is_discord_snowflake(channel_id):
            logger.warning("Invalid Discord channel ID format: %s", channel_id)
            return None

        if channel_id in self._channels:
            return self._channels[channel_id]

        channel = self._client.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self._client.fetch_channel(int(channel_id))
            except (discord.NotFound, discord.Forbidden, ValueError) as exc:
                logger.warning("Cannot access channel %s: %s", channel_id, exc)
                return None

        if not isinstance(channel, discord.abc.Messageable):
            logger.warning("Channel %s is not messageable", channel_id)
            return None

        self._channels[channel_id] = channel
        return channel

    async def _send_embed(
        self,
        channel: discord.abc.Messageable,
        embed: discord.Embed,
    ) -> bool:
        try:
            await channel.send(embed=embed)
            return True
        except discord.HTTPException as exc:
            logger.warning("Discord send failed: %s", exc)
            return False

    async def send_deal(self, search: SearchConfig, listing: Listing) -> bool:
        if not is_safe_ebay_listing_url(listing.url):
            logger.warning("Blocked non-eBay listing URL for %s", listing.item_id)
            return False

        channel = await self._resolve_channel(search.discord_channel_id)
        if channel is None:
            return False

        embed = build_deal_embed(search, listing)
        return await self._send_embed(channel, embed)

    async def send_near_miss(
        self,
        search: SearchConfig,
        listing: Listing,
        channel_id: str,
    ) -> bool:
        if not is_safe_ebay_listing_url(listing.url):
            logger.warning("Blocked non-eBay listing URL for %s", listing.item_id)
            return False

        channel = await self._resolve_channel(channel_id)
        if channel is None:
            return False

        over_target = listing.price.landed_cost - search.target_price
        over_pct = (over_target / search.target_price) * 100

        embed = discord.Embed(
            title=f"Near Miss: {search.id}"[:256],
            url=listing.url,
            color=0xF39C12,
            description=(
                f"**{over_pct:.1f}%** over target · "
                f"**£{over_target:.2f}** above £{search.target_price:.2f}"
            ),
        )
        embed.add_field(name="Price", value=f"£{listing.price.landed_cost:.2f}", inline=True)
        embed.add_field(name="Target", value=f"£{search.target_price:.2f}", inline=True)
        embed.add_field(name="Listed", value=_listed_ago(listing.listed_at), inline=True)

        if listing.image_url and is_safe_ebay_image_url(listing.image_url):
            embed.set_thumbnail(url=listing.image_url)

        embed.set_footer(text=f"{search.id} · {listing.item_id}")
        return await self._send_embed(channel, embed)

    async def _api_usage_slash(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if not _member_has_owner_access(interaction.user, self._owner_role_ids):
            await interaction.response.send_message(
                "You need the Owner role (or a configured owner role ID) to use this command.",
                ephemeral=True,
            )
            return

        now = time.monotonic()
        last = self._api_usage_last_call.get(interaction.user.id, 0.0)
        if now - last < API_USAGE_COOLDOWN_SECONDS:
            wait = int(API_USAGE_COOLDOWN_SECONDS - (now - last)) + 1
            await interaction.response.send_message(
                f"Please wait {wait}s before checking API usage again.",
                ephemeral=True,
            )
            return
        self._api_usage_last_call[interaction.user.id] = now

        calls_today = 0
        official_limit = None
        official_remaining = None

        if self._store:
            calls_today = self._store.get_today_api_calls()

        if self._ebay_client:
            rate_limits = await asyncio.to_thread(self._ebay_client.get_rate_limits)
            if rate_limits:
                try:
                    rate_limit_data = rate_limits.get("rateLimits", [])
                    for limit in rate_limit_data:
                        if limit.get("apiName", "").lower() == "browse":
                            for rate in limit.get("rates", []):
                                if rate.get("timeWindow") == 86400:
                                    official_limit = rate.get("limit")
                                    official_remaining = rate.get("remaining")
                                    break
                            break
                except Exception as exc:
                    logger.warning("Failed to parse rate limits response: %s", exc)

        limit = official_limit if official_limit else self._api_daily_limit
        percentage = (calls_today / limit) * 100 if limit > 0 else 0

        embed = discord.Embed(
            title="eBay API Usage",
            color=0x3498DB,
        )
        embed.add_field(name="Calls Today", value=str(calls_today), inline=True)
        embed.add_field(name="Daily Limit", value=str(limit), inline=True)
        embed.add_field(name="Usage", value=f"{percentage:.1f}%", inline=True)

        if official_remaining is not None:
            embed.add_field(
                name="Official Remaining",
                value=str(official_remaining),
                inline=True,
            )

        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
