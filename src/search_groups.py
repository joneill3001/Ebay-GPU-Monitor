from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from src.ebay_filters import build_aspect_filter, chipset_aspect_value
from src.models import SearchConfig

# Match Ti/Super before base when several variants share one API response.
_VARIANT_PRIORITY = {"ti": 0, "super": 1, "base": 2}


@dataclass
class SearchGroup:
    """One eBay API query; multiple GPU targets matched locally from the results."""

    id: str
    query: str
    api_max_price: float
    targets: list[SearchConfig]
    aspect_filter: str | None = None

    @property
    def target_labels(self) -> str:
        return ", ".join(t.id for t in self.targets)


def _group_query(family: str, model: str) -> str:
    prefix = "GTX" if family == "gtx" else "RTX"
    return f"{prefix} {model} graphics card"


def _build_aspect_filter_for_targets(targets: list[SearchConfig]) -> str:
    """Chipset/GPU Model aspect values for every variant in this search group."""
    values: list[str] = []
    for target in targets:
        if not target.match:
            continue
        values.append(
            chipset_aspect_value(
                target.match.model,
                target.match.variant,
                target.match.family,
            )
        )
    return build_aspect_filter(values)


def _sort_targets(targets: list[SearchConfig]) -> list[SearchConfig]:
    def priority(search: SearchConfig) -> int:
        if not search.match:
            return 99
        return _VARIANT_PRIORITY.get(search.match.variant, 50)

    return sorted(targets, key=priority)


def build_search_groups(searches: list[SearchConfig]) -> list[SearchGroup]:
    buckets: dict[tuple[str, str], list[SearchConfig]] = defaultdict(list)

    for search in searches:
        if not search.match:
            continue
        key = (search.match.family, search.match.model)
        buckets[key].append(search)

    groups: list[SearchGroup] = []
    for (family, model), bucket in sorted(buckets.items()):
        targets = _sort_targets(bucket)
        groups.append(
            SearchGroup(
                id=f"group-{family}-{model}",
                query=_group_query(family, model),
                api_max_price=max(t.target_price for t in targets),
                targets=targets,
                aspect_filter=_build_aspect_filter_for_targets(targets),
            )
        )

    return groups
