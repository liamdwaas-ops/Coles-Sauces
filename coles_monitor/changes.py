import hashlib
import json


FIELDS = ("name", "price", "size", "image_url", "online_only")


def stable_event_id(product_id, change_type, before, after):
    raw = json.dumps([str(product_id), change_type, before, after], ensure_ascii=False,
                     sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def compare(previous, current, observed_at, seen_event_ids=()):
    seen = set(seen_event_ids)
    events = []
    for product_id, product in sorted(current.items()):
        old = previous.get(product_id)
        if old is None:
            candidates = [("New product", "", product.get("name", ""))]
        else:
            candidates = []
            for field in FIELDS:
                before, after = old.get(field), product.get(field)
                if before != after:
                    label = "Online Only status" if field == "online_only" else field.replace("_url", "").title()
                    candidates.append((label + " changed", before, after))
        for change_type, before, after in candidates:
            event_id = stable_event_id(product_id, change_type, before, after)
            if event_id in seen:
                continue
            events.append({
                "event_id": event_id,
                "observed_at": observed_at,
                "product_id": product_id,
                "retailer": product.get("retailer", ""),
                "change_type": change_type,
                "before": before,
                "after": after,
                "name": product.get("name", ""),
                "price": product.get("price"),
                "size": product.get("size", ""),
                "image_url": product.get("image_url", ""),
                "online_only": bool(product.get("online_only")),
                "product_url": product.get("product_url", ""),
            })
    return events
