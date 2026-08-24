import re


def normalize(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_wanted_name(name):
    words = set(re.findall(r"[a-z]+", normalize(name).lower()))
    return (("pasta" in words and "sauce" in words)
            or ("tomato" in words and "paste" in words)
            or "pesto" in words
            or "passata" in words)


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

