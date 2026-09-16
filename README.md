# Coles and Woolworths sauce product change monitor

This repository checks these retailer category pages once a week:

- Coles: `https://www.coles.com.au/browse/pantry/sauces?sortBy=recommendedDescending`
- Woolworths: `https://www.woolworths.com.au/shop/browse/pantry/cooking-sauces-recipe-bases`

Every page is retrieved before the results are filtered to the report categories **Pasta Sauce**, **Tomato Paste**, **Passata** and **Pesto**. Classification uses the product title plus retailer-provided category taxonomy where available. This includes pasta-sauce products such as Woolworths' Leggo's Stir Through range even when the title itself omits the word `pasta`.

Products are excluded when the title contains the whole word `fresh`, when either the brand or title contains a configured ignored phrase, when their titles identify cooking utensils or decorative furniture, or when the retailer reports them as out of stock.

It records product-name, current-price, pack-size, ordered product-image and **Online Only** status changes, plus newly listed matching products. Image changes identify the affected retailer image position, such as `Image 2 changed` or `Image 4 added`. A new flavour with a new SKU is reported as **New**; a flavour rename on an existing SKU is reported as **Name**. This avoids guessing whether marketing text represents a flavour. Online-only promotions remain in the report and are labelled in the `Current Price` cell.

Each weekly email and the main Coles/Woolworths workbook sheets contain only SKUs that changed versus the previous successful weekly snapshot, with one row per changed SKU. Unchanged catalogue SKUs are omitted. Rows within each category are ordered by brand and then product name. The `Size` column sits immediately after the linked product name. A compact `Change Summary` distinguishes `RRP changed` from `Promotion` and combines simultaneous changes with labels such as `New`, `Image 2 changed`, `Unavailable`, or `Restocked`. Before, after and image columns are intentionally omitted; the separate `Change History` sheet remains the audit trail across runs.

When a SKU was promotional in the previous weekly snapshot and has returned to full price, that SKU is retained in the workbook audit trail but omitted from the email body. If a run contains only promotion-ending changes, no email is sent.

Current price, original price and percentage discount have separate columns. There is no redundant promotional-price or online-only column. Standard promotional prices already appear as `Current Price`; an online-only promotion is labelled there.

Explicit multibuy offers such as `2 for $14.00` are recorded verbatim in the `Current Price` column beside the single-item price. The discount percentage is calculated from the retailer-provided multibuy quantity and total against the current single-item price; no multibuy is inferred when the retailer does not provide an explicit offer.

Availability uses a two-location consensus. Cheltenham VIC 3192 is the primary location. Whenever Cheltenham is not fully available—or a previously agreed issue may be restocking—the monitor also checks Broadway NSW 2007. An availability issue is recorded only when both locations report the same issue. A mixed or unknown result preserves the last agreed state and produces no availability change. Likewise, restocking is recorded only after both locations report full availability. Agreed `Temporarily unavailable` or `No availability` states are shown once, suppressed while unchanged, and shown again only after a later agreed state change.

The configured primary location is **Cheltenham VIC 3192**, with **Broadway NSW 2007** as the availability backup. Coles resolves each locality through its public location service and uses the returned fulfilment store. Coles Broadway is store 839; its physical address is across the postcode boundary in Glebe 2037, so the resolver uses the nearest store returned for the exact Broadway 2007 locality when no store has the locality's exact postcode. Woolworths receives the relevant postcode in each anonymous category request; because that response does not identify the selected store, the monitor describes its values as Woolworths online availability/prices rather than claiming a particular store's shelf status.

The first successful run emails the complete baseline once. Later runs send an email only when at least one new, previously unreported change exists. Product names in the HTML email and Excel workbook link to their retailer product pages. No-change runs send nothing. Removed products are not treated as stock changes because absence from a category response is not reliable availability evidence; agreed two-location availability issues are reported under the consensus rule above.

## Shelf Seafood monitor

The repository also runs an independent **Shelf Seafood** monitor over these supplied category pages:

- Coles: `https://www.coles.com.au/browse/pantry/canned-food-soups-noodles/fish-seafood`
- Woolworths: `https://www.woolworths.com.au/shop/browse/pantry/canned-food-instant-meals/canned-tuna`
- Woolworths: `https://www.woolworths.com.au/shop/browse/pantry/canned-food-instant-meals/canned-salmon-seafood`

It applies the same pricing, promotion/multibuy, ordered-image, stock-consensus, change-only, deduplication and brand-ordering behavior as the Sauces monitor. It does not apply the sauce-specific keyword or ignored-brand filters: every valid SKU returned by the configured seafood category pages is eligible. Its email subject begins `Coles & Woolworths Shelf Seafood`, and its separate state and workbook are stored under `data/shelf-seafood/`.

## Schedule

Both workflows run at `20:00 UTC Tuesday`, which is **06:00 AEST Wednesday**. Because AEST is a fixed UTC+10 offset, this is 07:00 in Sydney when daylight saving (AEDT) applies. They share a concurrency group and run one after the other to prevent snapshot commit conflicts. GitHub Actions schedules can start a few minutes late under load.

## Required GitHub repository setup

1. Create a private GitHub repository and push this folder as its root.
2. In **Settings → Secrets and variables → Actions**, add:
   - `GMAIL_APP_PASSWORD`: a Google App Password for `liamdwaas@gmail.com` (never use or commit the normal Google password).
   - `COLES_BUILD_ID`: optional fallback containing the current Coles Next.js `buildId`. The normal Coles route uses its anonymous storefront APIs, so this is used only by the category-page compatibility fallback.
3. In **Settings → Actions → General → Workflow permissions**, select **Read and write permissions** so the workflow can commit its history.
4. Pushing the initial setup creates and emails the baseline. **Actions → Weekly Coles product monitor → Run workflow** remains available for diagnostics, but a manual run does not resend an existing baseline.

Google App Passwords require 2-Step Verification. If Google Workspace policy blocks App Passwords, use an approved SMTP relay and adapt `send_email` in `coles_monitor/reporting.py`.

## Data integrity behavior

- After a baseline exists, a temporarily blocked retailer retains its last verified records while the other retailer continues normally. The workflow emits a GitHub warning, never interprets the access failure as removals, and retries the retailer on the next scheduled run.
- Coles' flag comes from `pricing.onlineSpecial`/an online promotion label; Woolworths' flag comes from `IsOnlineOnly`. The monitor does not infer this status from price differences.
- Browser-compatible anonymous sessions are used for the retailers' public storefront data routes; no login, cart or checkout access is used. Coles first resolves the configured locality and sauce taxonomy, then paginates its official public storefront product API. Its server-rendered category data remains a compatibility fallback.
- The workflow does not use or require a retail proxy.
- Both category scrapers validate pagination against the retailer's reported total before accepting a snapshot. An incomplete category traversal fails safely and retains the last verified retailer snapshot.
- Change events have deterministic IDs and are stored in `data/events.json`, preventing duplicate reports.
- The complete audit history and current combined catalogue are kept in `data/coles-woolworths-sauce-change-history.xlsx` and uploaded as a workflow artifact.
- Every search includes postcode `3192` and delivery context. Prices should be treated as online prices returned for that location, not as a claim about shelf prices at an unspecified physical store.

## Local test

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python run_monitor.py --fixture tests/fixtures/week1.json --no-email
python run_monitor.py --fixture tests/fixtures/week2.json --no-email
```

The fixture names and URLs use the reserved `example.test` domain and are tests only; they are not Coles product claims.
