import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from coles_monitor.catalog import CombinedCategoryScraper
from coles_monitor.changes import compare, consolidate_events, visible_products
from coles_monitor.reporting import email_visible_events, send_email, write_workbook
from coles_monitor.scraper import ColesScraper
from coles_monitor.woolworths import WoolworthsScraper
from run_monitor import (apply_backup_availability, load_json, save_json,
                         scrape_with_fallback)


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "shelf-seafood"
WORKBOOK_FILENAME = "coles-woolworths-shelf-seafood-change-history.xlsx"


def configured_seafood_scrapers(config, location=None):
    selected_location = location or config.get("location")
    max_pages = config.get("max_pages_per_category", 30)
    delay = config["request_delay_seconds"]
    page_size = config["page_size"]
    categories = config["category_urls"]

    coles = CombinedCategoryScraper(
        ColesScraper(
            delay, max_pages, page_size, selected_location,
            config.get("coles_verified_build_id_fallback", ""),
            entry["url"], entry["group"],
        )
        for entry in categories["Coles"]
    )
    woolworths = CombinedCategoryScraper(
        WoolworthsScraper(
            delay, max_pages, page_size, selected_location,
            entry["url"], entry["group"],
        )
        for entry in categories["Woolworths"]
    )
    return coles, woolworths


def _valid_products(products):
    return {
        product_id: {**product, "product_id": product_id}
        for product_id, product in products.items()
        if product.get("name") and product.get("product_url") and
        product.get("category_group")
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--email-baseline", action="store_true")
    parser.add_argument("--source-smoke", action="store_true")
    parser.add_argument("--fixture", help="Use a local JSON product snapshot (tests only)")
    args = parser.parse_args()

    config = load_json(ROOT / "config-seafood.json", {})
    groups = config["report_groups"]
    report_name = config["report_name"]
    DATA.mkdir(parents=True, exist_ok=True)
    snapshot_path = DATA / "current.json"
    events_path = DATA / "events.json"
    workbook_path = DATA / WORKBOOK_FILENAME

    previous = _valid_products(load_json(snapshot_path, {}))
    history = consolidate_events(load_json(events_path, []))

    if args.source_smoke:
        counts = {}
        categories = {}
        for retailer, scraper in zip(("Coles", "Woolworths"),
                                     configured_seafood_scrapers(config)):
            products = scraper.scrape([])
            counts[retailer] = len(products)
            categories[retailer] = scraper.last_category_counts
        print(json.dumps({"shelf_seafood_source_smoke": counts,
                          "category_counts": categories}, sort_keys=True))
        return

    scrape_failures = []
    availability_warnings = []
    if args.fixture:
        current = load_json(Path(args.fixture), {})
    else:
        coles, woolworths = configured_seafood_scrapers(config)
        current, scrape_failures = scrape_with_fallback(
            (("Coles", coles), ("Woolworths", woolworths)), [], previous
        )
        failed_retailers = {failure.split(":", 1)[0] for failure in scrape_failures}
        current, availability_warnings = apply_backup_availability(
            current, previous, config, failed_retailers,
            scraper_factory=configured_seafood_scrapers,
        )
    current = _valid_products(current)

    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    first_run = not previous
    display_current = visible_products(previous, current, first_run)
    events = [] if first_run else compare(
        previous, current, observed_at, (event["event_id"] for event in history)
    )
    updated_history = history + events
    report_rows = list(display_current.values()) if first_run else events
    write_workbook(
        workbook_path, updated_history, display_current,
        report_events=report_rows, failures=scrape_failures, groups=groups,
    )
    save_json(snapshot_path, current)
    save_json(events_path, updated_history)
    print(json.dumps({
        "products": len(current), "changes": len(events), "baseline": first_run,
        "retailer_failures": scrape_failures,
        "availability_warnings": availability_warnings,
    }, sort_keys=True))

    if args.no_email:
        return
    body_events = email_visible_events(events)
    should_email = ((first_run and args.email_baseline) or
                    (not first_run and bool(body_events or scrape_failures)))
    if not should_email:
        return
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not password:
        raise RuntimeError("GMAIL_APP_PASSWORD is required when an email must be sent")
    send_email(
        config["sender"], config["recipient"], password, body_events,
        workbook_path, baseline=display_current if first_run else None,
        failures=scrape_failures, groups=groups, report_name=report_name,
        attachment_filename=WORKBOOK_FILENAME,
    )


if __name__ == "__main__":
    main()
