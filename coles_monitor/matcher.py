import re


def normalize(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_wanted_name(name):
    return keyword_group(name) is not None


def keyword_group(name):
    """Return one exclusive report group, ordered from most specific to broadest."""
    words = set(re.findall(r"[a-z]+", normalize(name).lower()))
    if "tomato" in words and "paste" in words:
        return "Tomato Paste"
    if "pasta" in words and "sauce" in words:
        return "Pasta Sauce"
    if "passata" in words:
        return "Passata"
    return None


def is_allowed_product(name, brand=""):
    words = set(re.findall(r"[a-z]+", normalize(name).lower()))
    excluded_brands = {"continental", "sirena"}
    return (is_wanted_name(name) and "fresh" not in words and
            normalize(brand).lower() not in excluded_brands)


def split_name_size(name, explicit_size=""):
    name = normalize(name)
    explicit_size = normalize(explicit_size)
    if explicit_size:
        suffix = re.compile(r"\s*\|?\s*" + re.escape(explicit_size) + r"\s*$", re.I)
        return normalize(suffix.sub("", name)), explicit_size
    match = re.search(r"\s*\|\s*([^|]+)$", name)
    if match:
        return normalize(name[:match.start()]), normalize(match.group(1))
    return name, ""
