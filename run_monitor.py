import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from coles_monitor.changes import compare
from coles_monitor.reporting import send_email, write_workbook
from coles_monitor.scraper import ColesScraper


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def load_json(path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--fixture", help="Use a local JSON product snapshot (tests only)")
    args = parser.parse_args()
    config = load_json(ROOT / "config.json", {})
    previous = load_json(DATA / "current.json", {})
    history = load_json(DATA / "events.json", [])
    if args.fixture:
        current = load_json(Path(args.fixture), {})
    else:
        scraper = ColesScraper(
            config["request_delay_seconds"], config["max_pages_per_query"],
            config["page_size"], config.get("location")
        )
        current = scraper.scrape(config["queries"])
    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    first_run = not previous
    events = [] if first_run else compare(
        previous, current, observed_at, (e["event_id"] for e in history)
    )
    updated_history = history + events
    workbook_path = DATA / "coles-product-change-history.xlsx"
    write_workbook(workbook_path, updated_history)
    save_json(DATA / "current.json", current)
    save_json(DATA / "events.json", updated_history)
    print(json.dumps({"products": len(current), "changes": len(events), "baseline": first_run}))
    if first_run or not events or args.no_email:
        return
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not password:
        raise RuntimeError("GMAIL_APP_PASSWORD is required when changes need to be emailed")
    send_email(config["sender"], config["recipient"], password, events, workbook_path)


if __name__ == "__main__":
    main()
