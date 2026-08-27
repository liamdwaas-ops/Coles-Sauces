import hashlib
import json


FIELDS = ("name", "price", "original_price", "promotional_price",
          "discount_percent", "size", "image_url", "online_only")
PRICE_FIELDS = {"price", "original_price", "promotional_price", "discount_percent"}
PRICE_CHANGE_TYPES = {"Price changed", "Original price changed",
                      "Promotional price changed", "Discount percentage changed"}


def summarize_change_type(change_type):
    summaries = {
        "Price changed": "Price",
        "Original price changed": "Price",
        "Promotional price changed": "Price",
        "Discount percentage changed": "Price",
        "Name changed": "Name",
        "Size changed": "Size",
        "Image changed": "Image",
        "Online Only status changed": "Online only",
        "New product": "New",
        "Temporarily unavailable": "Unavailable",
        "Back in stock": "Restocked",
    }
    return summaries.get(change_type, change_type)


def stable_event_id(product_id, change_type, before, after=None):
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
                    label = ("Price" if field in PRICE_FIELDS else
                             labels.get(field, field.replace("_url", "").title()))
                    raw_change_type = label + " changed"
                    candidates.append((summarize_change_type(raw_change_type), before, after))
        if candidates:
            change_type = "; ".join(dict.fromkeys(
                summarize_change_type(candidate[0]) for candidate in candidates
            ))
            changes = [(candidate[0], candidate[1], candidate[2]) for candidate in candidates]
            event_id = stable_event_id(product_id, change_type, changes)
            if event_id not in seen:
                events.append({
                "event_id": event_id,
                "observed_at": observed_at,
                "product_id": product_id,
                "retailer": product.get("retailer", ""),
                "change_type": change_type,
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


def consolidate_events(events):
    """Collapse legacy per-field events to one report row per SKU and observation."""
    grouped = {}
    order = []
    for event in events:
        key = (event.get("observed_at", ""), event.get("product_id", ""))
        if key not in grouped:
            grouped[key] = dict(event)
            grouped[key]["_types"] = []
            grouped[key]["_ids"] = []
            order.append(key)
        target = grouped[key]
        if event.get("event_id") and event["event_id"] not in target["_ids"]:
            target["_ids"].append(event["event_id"])
        for raw_change_type in str(event.get("change_type", "")).split("; "):
            change_type = summarize_change_type(raw_change_type)
            if change_type and change_type not in target["_types"]:
                target["_types"].append(change_type)
        for field, value in event.items():
            if value not in (None, ""):
                target[field] = value
    consolidated = []
    for key in order:
        event = grouped[key]
        event["change_type"] = "; ".join(event.pop("_types"))
        source_ids = event.pop("_ids")
        event.pop("before", None)
        event.pop("after", None)
        if len(source_ids) != 1:
            event["event_id"] = stable_event_id(
                event.get("product_id", ""), event["change_type"], sorted(source_ids)
            )
        consolidated.append(event)
    return consolidated


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
