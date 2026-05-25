from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

# Discord channel/user snowflakes (17–20 digits).
DISCORD_SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")

# UK outward + inward postcode, spaces removed (e.g. SW1A1AA).
UK_POSTCODE_RE = re.compile(r"^[A-Z0-9]{2,8}$")

EBAY_MARKETPLACES = frozenset(
    {"EBAY_GB", "EBAY_US", "EBAY_DE", "EBAY_AU", "EBAY_FR", "EBAY_IT", "EBAY_ES"}
)

EBAY_LISTING_HOSTS = frozenset(
    {
        "www.ebay.co.uk",
        "ebay.co.uk",
        "www.ebay.com",
        "ebay.com",
        "www.ebay.de",
        "ebay.de",
    }
)

EBAY_IMAGE_HOST_SUFFIXES = (".ebayimg.com", ".ebayimg.co.uk")

MAX_TITLE_LENGTH = 512
MAX_QUERY_LENGTH = 120
MAX_PRICE_GBP = 50_000.0


def is_discord_snowflake(value: str) -> bool:
    return bool(DISCORD_SNOWFLAKE_RE.match(value.strip()))


def normalize_uk_postcode(postcode: str) -> str:
    """Strip and uppercase; raises if characters are unsafe for eBay filter strings."""
    cleaned = postcode.strip().replace(" ", "").upper()
    if not cleaned:
        return ""
    if not UK_POSTCODE_RE.match(cleaned):
        raise ValueError(
            f"EBAY_DELIVERY_POSTCODE invalid: {postcode!r} — use a UK postcode (letters and digits only)"
        )
    return cleaned


def resolve_config_path(path: Path, project_root: Path, *, name: str) -> Path:
    """Resolve YAML/config paths and block directory traversal outside project root."""
    resolved = path.resolve() if path.is_absolute() else (project_root / path).resolve()
    root = project_root.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{name} must stay under the project directory: {resolved}")
    return resolved


def resolve_data_dir(path: Path, project_root: Path) -> Path:
    """Allow absolute data dirs outside the project; block traversal for relative paths."""
    if path.is_absolute():
        return path.resolve()
    resolved = (project_root / path).resolve()
    root = project_root.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"DATA_DIR must stay under the project directory: {resolved}")
    return resolved


def clamp_int(
    value: int,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


def clamp_float(
    value: float,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


def sanitize_title(title: str) -> str:
    if len(title) > MAX_TITLE_LENGTH:
        return title[:MAX_TITLE_LENGTH]
    return title


def sanitize_search_query(query: str) -> str:
    q = query.strip()
    if not q:
        raise ValueError("Search query must not be empty")
    if len(q) > MAX_QUERY_LENGTH:
        return q[:MAX_QUERY_LENGTH]
    return q


def is_safe_ebay_listing_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return host in EBAY_LISTING_HOSTS


def is_safe_ebay_image_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return any(host.endswith(suffix) for suffix in EBAY_IMAGE_HOST_SUFFIXES)
