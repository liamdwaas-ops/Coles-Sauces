import hashlib
import json


FIELDS = ("name", "price", "original_price", "promotional_price",
          "discount_percent", "size", "image_url", "online_only")


def stable_event_id(product_id, change_type, before, after):
    raw = json.dumps([str(product_id), change_type, before, after], ensure_ascii=False,
                     sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def compare(previous, current, observed_at, seen_event_ids=()):
    seen = set(seen_event_ids)
    events = []
    for product_id, product in sorted(current.items()):
        old = previous.get(product_id)
        current_status = product.get("availability_state", "in_stock")
        old_status = old.get("availability_state", "in_stock") if old else None
        if current_status == "out_of_stock":
            continue
        if current_status == "temporary_unavailable":
            if old_status == "temporary_unavailable":
                continue
            candidates = [("Temporarily unavailable", old_status or "", "Temporarily unavailable")]
        elif old_status in {"temporary_unavailable", "out_of_stock"}:
            candidates = [("Back in stock", old.get("availability_label", old_status),
                           product.get("availability_label", "Available"))]
        elif old is None:
            candidates = [("New product", "", product.get("name", ""))]
        else:
            candidates = []
            for field in FIELDS:
                before, after = old.get(field), product.get(field)
                if before != after:
                    labels = {
                        "online_only": "Online Only status",
                        "original_price": "Original price",
                        "promotional_price": "Promotional price",
                        "discount_percent": "Discount percentage",
                    }
                    label = labels.get(field, field.replace("_url", "").title())
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
                "brand": product.get("brand", ""),
                "price": product.get("price"),
                "original_price": product.get("original_price"),
                "promotional_price": product.get("promotional_price"),
                "discount_percent": product.get("discount_percent"),
                "availability_label": product.get("availability_label", ""),
                "size": product.get("size", ""),
                "image_url": product.get("image_url", ""),
                "online_only": bool(product.get("online_only")),
                "product_url": product.get("product_url", ""),
            })
    return events


def visible_products(previous, current, first_run=False):
    visible = {}
    for product_id, product in current.items():
        status = product.get("availability_state", "in_stock")
        old = previous.get(product_id)
        old_status = old.get("availability_state", "in_stock") if old else None
        if status == "in_stock":
            visible[product_id] = product
        elif status == "temporary_unavailable" and (first_run or old_status != status):
            visible[product_id] = product
    return visible
