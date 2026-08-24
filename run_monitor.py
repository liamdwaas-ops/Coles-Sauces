import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from coles_monitor.changes import compare
from coles_monitor.reporting import send_email, write_workbook
from coles_monitor.scraper import ColesScraper
from coles_monitor.woolworths import WoolworthsScraper


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
    parser.add_argument("--email-baseline", action="store_true")
    parser.add_argument("--send-existing-baseline", action="store_true")
    parser.add_argument("--fixture", help="Use a local JSON product snapshot (tests only)")
    args = parser.parse_args()
    config = load_json(ROOT / "config.json", {})
    previous = load_json(DATA / "current.json", {})
    history = load_json(DATA / "events.json", [])
    workbook_path = DATA / "coles-woolworths-sauce-change-history.xlsx"
    if args.send_existing_baseline:
        if not previous or not workbook_path.exists():
            raise RuntimeError("An existing baseline snapshot and workbook are required")
        password = os.environ.get("GMAIL_APP_PASSWORD", "")
        if not password:
            raise RuntimeError("GMAIL_APP_PASSWORD is required to email the baseline")
        send_email(config["sender"], config["recipient"], password, [], workbook_path,
                   baseline=previous)
        print(json.dumps({"baseline_email_products": len(previous)}))
        return
    if args.fixture:
        current = load_json(Path(args.fixture), {})
    else:
        coles = ColesScraper(
            config["request_delay_seconds"], config["max_pages_per_query"],
            config["page_size"], config.get("location"),
            config.get("coles_verified_build_id_fallback", "")
        )
        woolworths = WoolworthsScraper(
            config["request_delay_seconds"], config["max_pages_per_query"],
            config["page_size"], config.get("location")
        )
        current = coles.scrape(config["queries"])
        current.update(woolworths.scrape(config["queries"]))
    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    first_run = not previous
    events = [] if first_run else compare(
        previous, current, observed_at, (e["event_id"] for e in history)
    )
    updated_history = history + events
    write_workbook(workbook_path, updated_history, current)
    save_json(DATA / "current.json", current)
    save_json(DATA / "events.json", updated_history)
    print(json.dumps({"products": len(current), "changes": len(events), "baseline": first_run}))
    if args.no_email:
        return
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    should_email = (first_run and args.email_baseline) or (not first_run and bool(events))
    if not should_email:
        return
    if not password:
        raise RuntimeError("GMAIL_APP_PASSWORD is required when changes need to be emailed")
    send_email(config["sender"], config["recipient"], password, events, workbook_path,
               baseline=current if first_run else None)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        message = str(exc).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title=Monitor failure::{type(exc).__name__}: {message}", file=sys.stderr)
        raise
