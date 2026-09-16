FULLY_AVAILABLE = "in_stock"
UNKNOWN = "unknown"


def location_label(location):
    return " ".join(
        str(location.get(key, "")).strip()
        for key in ("suburb", "state", "postcode")
        if str(location.get(key, "")).strip()
    )


def availability_backup_required(primary, previous):
    """Check the backup when primary is impaired or a prior issue may be restocking."""
    for product_id, product in primary.items():
        current_state = product.get("availability_state", FULLY_AVAILABLE)
        old = previous.get(product_id)
        old_state = old.get("availability_state", FULLY_AVAILABLE) if old else FULLY_AVAILABLE
        if current_state != FULLY_AVAILABLE or old_state != FULLY_AVAILABLE:
            return True
    return False


def _location_status(product):
    if not product:
        return {"state": UNKNOWN, "label": "Not returned by the location catalogue"}
    state = product.get("availability_state", FULLY_AVAILABLE)
    label = product.get("availability_label") or (
        "Available" if state == FULLY_AVAILABLE else state.replace("_", " ").title()
    )
    return {"state": state, "label": label}


def apply_availability_consensus(primary, backup, previous,
                                 primary_location, backup_location):
    """Use an agreed two-location state, preserving the last consensus when mixed.

    Products that are fully available at the primary location do not require a backup
    result unless the prior agreed state was impaired and therefore needs a confirmed
    two-location restock.
    """
    primary_name = location_label(primary_location)
    backup_name = location_label(backup_location)
    merged = {}
    for product_id, source_product in primary.items():
        product = dict(source_product)
        old = previous.get(product_id)
        old_state = old.get("availability_state", FULLY_AVAILABLE) if old else FULLY_AVAILABLE
        has_prior_consensus = bool(old and old.get("availability_consensus"))
        if old and not has_prior_consensus:
            # The saved snapshot predates dual-location checking. Do not turn
            # that single-location state into a false consensus transition.
            product["availability_consensus_migration"] = True
        primary_status = _location_status(product)
        needs_backup = (primary_status["state"] != FULLY_AVAILABLE or
                        old_state != FULLY_AVAILABLE)
        locations = {primary_name: primary_status}

        if not needs_backup:
            product["availability_locations"] = locations
            product["availability_consensus"] = "primary_fully_available"
            merged[product_id] = product
            continue

        backup_product = backup.get(product_id)
        backup_status = _location_status(backup_product)
        locations[backup_name] = backup_status
        product["availability_locations"] = locations

        primary_state = primary_status["state"]
        backup_state = backup_status["state"]
        if primary_state == backup_state and backup_state != UNKNOWN:
            product["availability_state"] = primary_state
            if primary_state == FULLY_AVAILABLE:
                product["availability_label"] = (
                    f"Available in {primary_name} and {backup_name}"
                )
            elif primary_state == "out_of_stock":
                product["availability_label"] = (
                    f"No availability in {primary_name} and {backup_name}"
                )
            elif primary_state == "temporary_unavailable":
                product["availability_label"] = (
                    f"Temporarily unavailable in {primary_name} and {backup_name}"
                )
            else:
                product["availability_label"] = (
                    f"{primary_status['label']} in {primary_name} and {backup_name}"
                )
            product["availability_consensus"] = "locations_agree"
        else:
            # A mixed or unknown result is not an agreed change. Keep the last
            # consensus so an issue/restock is emitted only after both locations agree.
            preserved_state = old_state if has_prior_consensus else FULLY_AVAILABLE
            product["availability_state"] = preserved_state
            product["availability_label"] = (
                old.get("availability_label") if has_prior_consensus else "Available"
            ) or ("Available" if preserved_state == FULLY_AVAILABLE else
                  preserved_state.replace("_", " ").title())
            product["availability_consensus"] = "mixed_preserved"
        merged[product_id] = product
    return merged
