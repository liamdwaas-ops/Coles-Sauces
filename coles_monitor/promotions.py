import re

from .matcher import normalize


MULTIBUY_PATTERN = re.compile(
    r"(?:pick\s+any\s+)?\d+\s+(?:items?\s+)?for\s+\$\s*\d+(?:\.\d{1,2})?",
    re.I,
)


def find_multibuy_text(value):
    """Return only an explicit retailer-provided 'N for $X' offer."""
    if isinstance(value, dict):
        priority = ("offerDescription", "OfferDescription", "PromotionDescription",
                    "PromotionText", "CentreTag", "HeaderTag", "FooterTag")
        for key in priority:
            if key in value:
                found = find_multibuy_text(value[key])
                if found:
                    return found
        for child in value.values():
            found = find_multibuy_text(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_multibuy_text(child)
            if found:
                return found
    elif isinstance(value, str):
        match = MULTIBUY_PATTERN.search(value)
        if match:
            return normalize(match.group(0)).replace("$ ", "$")
    return ""


def multibuy_unit_price(text):
    match = re.search(r"(\d+)\s+(?:items?\s+)?for\s+\$\s*(\d+(?:\.\d{1,2})?)", text, re.I)
    if not match or int(match.group(1)) <= 0:
        return None
    return float(match.group(2)) / int(match.group(1))
