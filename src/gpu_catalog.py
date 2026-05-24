from __future__ import annotations

from dataclasses import dataclass

# xx60–xx90 only (no xx50 / xx30 budget tiers). Ti and Super where NVIDIA shipped them.
GPU_CATALOG: tuple[tuple[str, str, str, str], ...] = (
    # (key, model, variant, family)  family = gtx | rtx
    # 10 series (GTX)
    ("1060", "1060", "base", "gtx"),
    ("1070", "1070", "base", "gtx"),
    ("1080", "1080", "base", "gtx"),
    ("1080-ti", "1080", "ti", "gtx"),
    # 20 series (RTX)
    ("2060", "2060", "base", "rtx"),
    ("2060-super", "2060", "super", "rtx"),
    ("2070", "2070", "base", "rtx"),
    ("2070-super", "2070", "super", "rtx"),
    ("2080", "2080", "base", "rtx"),
    ("2080-ti", "2080", "ti", "rtx"),
    ("2080-super", "2080", "super", "rtx"),
    # 30 series (RTX)
    ("3060", "3060", "base", "rtx"),
    ("3060-ti", "3060", "ti", "rtx"),
    ("3070", "3070", "base", "rtx"),
    ("3070-ti", "3070", "ti", "rtx"),
    ("3080", "3080", "base", "rtx"),
    ("3080-ti", "3080", "ti", "rtx"),
    ("3090", "3090", "base", "rtx"),
    ("3090-ti", "3090", "ti", "rtx"),
    # 40 series (RTX)
    ("4060", "4060", "base", "rtx"),
    ("4060-ti", "4060", "ti", "rtx"),
    ("4070", "4070", "base", "rtx"),
    ("4070-ti", "4070", "ti", "rtx"),
    ("4070-super", "4070", "super", "rtx"),
    ("4080", "4080", "base", "rtx"),
    ("4080-super", "4080", "super", "rtx"),
    ("4090", "4090", "base", "rtx"),
    # 50 series (RTX)
    ("5060", "5060", "base", "rtx"),
    ("5060-ti", "5060", "ti", "rtx"),
    ("5070", "5070", "base", "rtx"),
    ("5070-ti", "5070", "ti", "rtx"),
    ("5080", "5080", "base", "rtx"),
    ("5090", "5090", "base", "rtx"),
)

# Map series number -> prices.yaml channels key (one Discord channel per series)
SERIES_CHANNEL_GROUP: dict[int, str] = {
    10: "10",
    20: "20",
    30: "30",
    40: "40",
    50: "50",
}


@dataclass(frozen=True)
class GpuDefinition:
    key: str
    model: str
    variant: str
    family: str
    series: int

    @property
    def search_id(self) -> str:
        return f"{self.family}-{self.key}"

    @property
    def ebay_query(self) -> str:
        prefix = "GTX" if self.family == "gtx" else "RTX"
        if self.variant == "base":
            return f"{prefix} {self.model}"
        label = self.variant.upper() if self.variant == "ti" else "Super"
        return f"{prefix} {self.model} {label}"


def _series_from_model(model: str, family: str) -> int:
    if family == "gtx":
        return 10
    return int(model[:2])


def iter_gpu_definitions() -> list[GpuDefinition]:
    items: list[GpuDefinition] = []
    for key, model, variant, family in GPU_CATALOG:
        series = _series_from_model(model, family)
        items.append(
            GpuDefinition(
                key=key,
                model=model,
                variant=variant,
                family=family,
                series=series,
            )
        )
    return items


def channel_group_for_series(series: int) -> str:
    return SERIES_CHANNEL_GROUP.get(series, "30")
