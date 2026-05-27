from __future__ import annotations

import re

from src.models import MatchConfig
from src.validation import sanitize_title

# Titles matching any of these are never treated as a complete GPU.
_REJECT_PATTERNS: list[re.Pattern[str]] = [
    # Condition / faulty
    re.compile(r"\bfor\s+parts\b", re.I),
    re.compile(r"\bfor\s+spares?\b", re.I),
    re.compile(r"\bparts?\s+only\b", re.I),
    re.compile(r"\bspares?\s+only\b", re.I),
    re.compile(r"\bnot\s+working\b", re.I),
    re.compile(r"\bnon\s*working\b", re.I),
    re.compile(r"\bdoesn'?t\s+work\b", re.I),
    re.compile(r"\bdo\s+not\s+work\b", re.I),
    re.compile(r"\bas\s+is\b", re.I),
    re.compile(r"\buntested\b", re.I),
    re.compile(r"\bno\s+power\b", re.I),
    re.compile(r"\bwon'?t\s+power\b", re.I),
    re.compile(r"\bfor\s+repair\b", re.I),
    re.compile(r"\brepair\s+only\b", re.I),
    re.compile(r"\bscrap\b", re.I),
    re.compile(r"\bfaulty\b", re.I),
    re.compile(r"\bbroken\b", re.I),
    re.compile(r"\bdamaged\b", re.I),
    re.compile(r"\bcracked\b", re.I),
    re.compile(r"\bbent\b", re.I),
    re.compile(r"\bartefacts?\b", re.I),
    re.compile(r"\bartifacts?\b", re.I),
    re.compile(r"\bno\s+display\b", re.I),
    re.compile(r"\bdisplay\s+issue", re.I),
    re.compile(r"\bdead\b", re.I),
    re.compile(r"\bdefective\b", re.I),
    # Missing GPU / PCB-only
    re.compile(r"\bno\s+chip\b", re.I),
    re.compile(r"\bno\s+gpu\b", re.I),
    re.compile(r"\bwithout\s+(?:gpu|chip|core|processor)\b", re.I),
    re.compile(r"\bmissing\s+(?:gpu|chip|core|processor)\b", re.I),
    re.compile(r"\bblank\s+pcb\b", re.I),
    re.compile(r"\bempty\s+pcb\b", re.I),
    re.compile(r"\bpcba\s+only\b", re.I),
    re.compile(r"\bpcb\s+only\b", re.I),
    re.compile(r"\bboard\s+only\b", re.I),
    re.compile(r"\bpcie\s+board\s+only\b", re.I),
    re.compile(r"\bmainboard\s+only\b", re.I),
    re.compile(r"\bno\s+core\b", re.I),
    re.compile(r"\bcore\s+only\b", re.I),
    re.compile(r"\bprocessor\s+only\b", re.I),
    re.compile(r"\bchip\s+only\b", re.I),
    re.compile(r"\bunit\s+only\b", re.I),
    re.compile(r"\bno\s+memory\b", re.I),
    re.compile(r"\bmemory\s+missing\b", re.I),
    # Parts / accessories (often "only")
    re.compile(r"\bfans?\s+only\b", re.I),
    re.compile(r"\bonly\s+fans?\b", re.I),
    re.compile(r"\bheatsink\s+only\b", re.I),
    re.compile(r"\bheat\s*sink\s+only\b", re.I),
    re.compile(r"\bcooler\s+only\b", re.I),
    re.compile(r"\bonly\s+cooler\b", re.I),
    re.compile(r"\bwater\s*block\s+only\b", re.I),
    re.compile(r"\bwaterblock\s+only\b", re.I),
    re.compile(r"\bcooling\s+block\s+only\b", re.I),
    re.compile(r"\bblock\s+only\b", re.I),
    re.compile(r"\bwater\s*block\b", re.I),
    re.compile(r"\bwaterblock\b", re.I),
    re.compile(r"\bek\s+wb\b", re.I),
    re.compile(r"\bshroud\s+only\b", re.I),
    re.compile(r"\bbackplate\s+only\b", re.I),
    re.compile(r"\bbracket\s+only\b", re.I),
    re.compile(r"\bplate\s+only\b", re.I),
    re.compile(r"\bretention\s+bracket\b", re.I),
    re.compile(r"\bholder\s+only\b", re.I),
    re.compile(r"\bscrews?\s+only\b", re.I),
    re.compile(r"\bthermal\s+paste\s+only\b", re.I),
    re.compile(r"\bcover\s+only\b", re.I),
    re.compile(r"\bshell\s+only\b", re.I),
    re.compile(r"\bbox\s+only\b", re.I),
    re.compile(r"\bempty\s+box\b", re.I),
    re.compile(r"\bpackaging\s+only\b", re.I),
    re.compile(r"\bmanual\s+only\b", re.I),
    re.compile(r"\bcable\s+only\b", re.I),
    re.compile(r"\briser\b", re.I),
    re.compile(r"\bmining\b", re.I),
    re.compile(r"\bhashboard\b", re.I),
    re.compile(r"\bcontroller\s+card\b", re.I),
    re.compile(r"\binterface\s+card\b", re.I),
    re.compile(r"\badapter\s+plate\b", re.I),
    re.compile(r"\bpower\s+board\b", re.I),
    re.compile(r"\bvrm\b", re.I),
    re.compile(r"\bcapacitors?\b", re.I),
    re.compile(r"\bcoil\b", re.I),
    re.compile(r"\bport\s+only\b", re.I),
    re.compile(r"\bhdmi\s+only\b", re.I),
    re.compile(r"\bdisplayport\s+only\b", re.I),
    re.compile(r"\bi/?o\s+bracket\b", re.I),
    re.compile(r"\bcooling\s+system\b", re.I),
    re.compile(r"\b(?:hdmi|displayport|display\s+port|dp)\s+port\b", re.I),
    re.compile(r"\bport\s+replacement\b", re.I),
    re.compile(r"\breplacement\s+(?:hdmi|displayport|display\s+port|dp|io|i/o)\b", re.I),
    re.compile(r"\breplacement\s+port\b", re.I),
    re.compile(r"\bupgrade\s+kit\b", re.I),
    re.compile(r"\brepair\s+kit\b", re.I),
    re.compile(r"\bradiator\s+only\b", re.I),
    re.compile(r"\breservoir\b", re.I),
    re.compile(r"\bpump\s+only\b", re.I),
    re.compile(r"\bloop\s+only\b", re.I),
    re.compile(r"\bcustom\s+loop\b", re.I),
    re.compile(r"\bfake\b", re.I),
    re.compile(r"\breplica\b", re.I),
    re.compile(r"\bcounterfeit\b", re.I),
    re.compile(r"\bart\s+card\b", re.I),
    re.compile(r"\bpaperweight\b", re.I),
    re.compile(r"\bsticker\b", re.I),
    re.compile(r"\bdecal\b", re.I),
    re.compile(r"\bposter\b", re.I),
    # xx50 / budget tiers (not scanned, but block if eBay returns them)
    re.compile(r"\b(?:gtx|rtx)\s*1030\b", re.I),
    re.compile(r"\b(?:gtx|rtx)\s*1050\b", re.I),
    re.compile(r"\bgtx\s*1650\b", re.I),
    re.compile(r"\brtx\s*2050\b", re.I),
    re.compile(r"\brtx\s*3050\b", re.I),
    re.compile(r"\brtx\s*4050\b", re.I),
    re.compile(r"\brtx\s*5050\b", re.I),
]

_ACCESSORY_PATTERNS = [
    re.compile(r"\bfor\s+(?:the\s+)?(?:nvidia\s+)?(?:gtx|rtx)\s+\d{4}", re.I),
    re.compile(r"\bcompatible\s+with\b", re.I),
    re.compile(r"\bfits\s+(?:the\s+)?(?:nvidia\s+)?(?:gtx|rtx)\b", re.I),
    re.compile(r"\bcase\s+for\b", re.I),
    re.compile(r"\bcover\s+for\b", re.I),
    re.compile(r"\bsuitable\s+for\b", re.I),
    re.compile(r"\breplacement\s+for\b", re.I),
    re.compile(r"\breplacement\b", re.I),
    re.compile(r"\bfan\s+for\b", re.I),
    re.compile(r"\bcooling\s+fan\b", re.I),
    re.compile(r"\bheatsink\s+fan\b", re.I),
    re.compile(r"\bwith\s+heatsink\s+and\s+fan\b", re.I),
    re.compile(r"\b(?:sold|selling)\s+separately\b", re.I),
]

_STRONG_CARD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bgraphics\s+card\b", re.I),
    re.compile(r"\bvideo\s+card\b", re.I),
    re.compile(r"\bgaming\s+(?:oc\s+)?(?:graphics|video)\s+card\b", re.I),
    re.compile(r"\bworkstation\s+card\b", re.I),
]

# Water-cooled full cards often omit "graphics card" but include VRAM + AIB branding.
_WATERCOOLED_CARD_HINT = re.compile(
    r"\b(?:hydro|aio|liquid|water\s*cooled?|watercool(?:ed)?)\b.*\b\d{1,2}\s*gb\b",
    re.I,
)

_AIB_BRAND_PATTERN = re.compile(
    r"\b(asus|msi|gigabyte|zotac|evga|palit|pny|galax|kfa2|inno3d|gainward|"
    r"nvidia|founders\s+edition|colorful|maxsun|yeston)\b",
    re.I,
)
_VRAM_PATTERN = re.compile(r"\b\d{1,2}\s*gb\b", re.I)


def normalize_title(title: str) -> str:
    text = title.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _word_match(term: str, text: str) -> bool:
    term = term.lower().strip()
    if " " in term:
        pattern = rf"\b{re.escape(term)}\b"
    else:
        pattern = rf"\b{re.escape(term)}\b"
    return re.search(pattern, text) is not None


def _build_model_pattern(model: str, variant: str) -> re.Pattern[str]:
    model_esc = re.escape(model)

    chip = r"(?:gtx|rtx|geforce|nvidia)"

    if variant == "ti":
        return re.compile(
            rf"\b(?:nvidia\s+)?(?:geforce\s+)?(?:{chip}\s+)?{model_esc}\s*ti\b",
            re.I,
        )
    if variant == "super":
        return re.compile(
            rf"\b(?:nvidia\s+)?(?:geforce\s+)?(?:{chip}\s+)?{model_esc}\s*super\b",
            re.I,
        )
    if variant == "any":
        return re.compile(
            rf"\b(?:nvidia\s+)?(?:geforce\s+)?(?:{chip}\s+)?{model_esc}(?:\s*(?:ti|super))?\b",
            re.I,
        )

    return re.compile(
        rf"\b(?:nvidia\s+)?(?:geforce\s+)?(?:{chip}\s+)?{model_esc}\b(?!\s*(?:ti|super|m\b))",
        re.I,
    )


def _reject_wrong_variant(title: str, model: str, variant: str) -> bool:
    normalized = normalize_title(title)
    model_esc = re.escape(model)

    if variant == "base":
        if re.search(rf"\b{model_esc}\s*ti\b", normalized):
            return True
        if re.search(rf"\b{model_esc}\s*super\b", normalized):
            return True
        if re.search(rf"\b{model_esc}m\b", normalized):
            return True
    elif variant == "ti":
        if re.search(rf"\b{model_esc}\s*super\b", normalized):
            return True
    return False


def _matches_reject_patterns(title: str) -> bool:
    for pattern in _REJECT_PATTERNS:
        if pattern.search(title):
            return True
    return False


def _looks_like_complete_gpu(title: str) -> bool:
    """Require strong evidence this is a full graphics card, not a part or kit."""
    if any(p.search(title) for p in _STRONG_CARD_PATTERNS):
        return True
    if _WATERCOOLED_CARD_HINT.search(title):
        return True

    normalized = normalize_title(title)
    has_brand = _AIB_BRAND_PATTERN.search(normalized) is not None
    has_vram = _VRAM_PATTERN.search(normalized) is not None
    has_chip = re.search(r"\b(?:gtx|rtx)\s*\d{4}", normalized) is not None

    if has_brand and has_vram and has_chip:
        return True
    if has_vram and has_chip and re.search(r"\bgeforce\b", normalized):
        return True
    return False


def explain_title_match(
    title: str, config: MatchConfig, condition: str | None = None
) -> tuple[bool, str]:
    title = sanitize_title(title)
    normalized = normalize_title(title)

    if _matches_reject_patterns(title):
        return False, "reject_pattern"

    # Filter by eBay condition - only allow New (1000), Used (1000-2000), or Open Box (1500)
    # Reject: For parts or not working (7000), Seller Refurbished (2000), etc.
    if condition:
        # eBay condition IDs: 1000=New, 1500=Open Box, 2000-2500=Used, 7000=For parts/not working
        # We only want: New, Open Box, and Used conditions
        allowed_conditions = {
            "1000", "1500", "2000", "2010", "2020", "2030", "2040", "2050", "2500",
            "3000", "4000", "5000", "6000",
        }
        if condition not in allowed_conditions:
            return False, f"condition_disallowed:{condition}"

    for term in config.require_terms:
        if not _word_match(term, normalized):
            return False, f"missing_required:{term}"

    for term in config.exclude_terms:
        if _word_match(term, normalized):
            return False, f"banned_word:{term}"

    for pattern in _ACCESSORY_PATTERNS:
        if pattern.search(title):
            return False, "accessory_pattern"

    model_pattern = _build_model_pattern(config.model, config.variant)
    if not model_pattern.search(title):
        return False, "model_mismatch"

    if _reject_wrong_variant(title, config.model, config.variant):
        return False, "wrong_variant"

    if not _looks_like_complete_gpu(title):
        return False, "incomplete_gpu_evidence"

    return True, "accepted"


def matches_title(title: str, config: MatchConfig, condition: str | None = None) -> bool:
    ok, _ = explain_title_match(title, config, condition)
    return ok
