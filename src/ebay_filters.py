from __future__ import annotations

"""eBay Browse API filter strings (field filters + aspect_filter)."""

# Computer Graphics Cards
GRAPHICS_CARD_CATEGORY_ID = 27386

# Must match eBay category 27386 refinement name exactly.
CHIPSET_ASPECT_NAME = "Chipset/GPU Model"

# conditionIds allowlist — excludes 7000 (For parts / not working).
# Include 3000–6000: many UK Used listings only expose generic Used (3000), not 2000–2050.
ALLOWED_CONDITION_IDS: tuple[str, ...] = (
    "1000",  # New
    "1500",  # Open box / New other
    "2000",
    "2010",
    "2020",
    "2030",
    "2040",
    "2050",
    "2500",  # Seller refurbished
    "3000",  # Used (generic)
    "4000",  # Very Good
    "5000",  # Good
    "6000",  # Acceptable
)

_CONDITION_IDS_FILTER = f"conditionIds:{{{'|'.join(ALLOWED_CONDITION_IDS)}}}"


def chipset_aspect_value(model: str, variant: str, family: str) -> str:
    """Canonical Chipset/GPU Model value as used in eBay category 27386 refinements."""
    prefix = "GTX" if family == "gtx" else "RTX"
    base = f"NVIDIA GeForce {prefix} {model}"
    if variant == "ti":
        return f"{base} Ti"
    if variant == "super":
        return f"{base} Super"
    return base


def build_aspect_filter(chipset_values: list[str]) -> str:
    """aspect_filter for item_summary/search (categoryId required twice)."""
    if not chipset_values:
        raise ValueError("chipset_values must not be empty")
    unique = list(dict.fromkeys(chipset_values))
    values = "|".join(unique)
    return (
        f"categoryId:{GRAPHICS_CARD_CATEGORY_ID},"
        f"{CHIPSET_ASPECT_NAME}:{{{values}}}"
    )


def build_field_filter(
    max_price: float,
    *,
    delivery_postcode: str = "",
    include_conditions: bool = True,
) -> str:
    """Comma-separated field filters for the filter query parameter."""
    max_int = int(max_price)
    parts = [
        "deliveryCountry:GB",
        f"price:[..{max_int}]",
        "priceCurrency:GBP",
    ]
    if delivery_postcode:
        parts.insert(1, f"deliveryPostalCode:{delivery_postcode}")
    if include_conditions:
        parts.append(_CONDITION_IDS_FILTER)
    return ",".join(parts)


def field_filter_fallbacks(
    max_price: float,
    delivery_postcode: str,
) -> list[tuple[str, bool]]:
    """(filter string, include_conditions) from strictest to loosest."""
    postcode = delivery_postcode.replace(" ", "").upper()
    variants: list[tuple[str, bool]] = []

    if postcode:
        variants.append(
            (build_field_filter(max_price, delivery_postcode=postcode, include_conditions=True), True)
        )
    variants.append(
        (build_field_filter(max_price, include_conditions=True), True)
    )
    if postcode:
        variants.append(
            (
                build_field_filter(
                    max_price,
                    delivery_postcode=postcode,
                    include_conditions=False,
                ),
                False,
            )
        )
    variants.append(
        (build_field_filter(max_price, include_conditions=False), False)
    )
    variants.append((f"deliveryCountry:GB,price:[..{int(max_price)}]", False))
    return variants
