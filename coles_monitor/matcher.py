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
    if "pesto" in words:
        return "Pesto"
    return None


def is_allowed_product(name, brand=""):
    normalized_name = normalize(name).lower()
    words = set(re.findall(r"[a-z]+", normalize(name).lower()))
    excluded_brands = {
        "continental", "sirena", "capsicana", "latina", "san remo", "tandaco",
        "my muscle", "my muscle chef", "coles made easy", "fitness outcomes",
        "coles kitchen", "black swan", "rana", "red rock deli", "coles perform",
        "cucina", "youfoodz", "prepara", "porto", "tovolo", "hot shot", "easy eats",
    }
    excluded_non_food_words = {
        "chopper", "mandoline", "grater", "peeler", "utensil", "knife", "knives",
        "scissors", "spatula", "spoon", "ladle", "tongs", "whisk", "colander",
        "strainer", "cookware", "rug", "cushion", "chair", "stool", "lamp", "vase",
        "planter", "furniture",
    }
    excluded_title_phrases = excluded_brands | {"manual food chopper", "throw rug"}
    return (is_wanted_name(name) and "fresh" not in words and
            not words.intersection(excluded_non_food_words) and
            not any(re.search(r"\b" + re.escape(phrase) + r"\b", normalized_name)
                    for phrase in excluded_title_phrases) and
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
