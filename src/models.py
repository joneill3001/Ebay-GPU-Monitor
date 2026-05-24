from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MatchConfig:
    model: str
    variant: str = "base"
    family: str = "rtx"
    require_terms: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)


@dataclass
class SearchConfig:
    id: str
    query: str
    target_price: float
    discord_channel_id: str
    enabled: bool = True
    max_listing_age_minutes: int = 45
    match: MatchConfig | None = None
