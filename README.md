# Coles and Woolworths sauce product change monitor

This repository checks Coles and Woolworths once a week for products whose **name** matches one of these rules:

- contains both whole words `pasta` and `sauce` (in any order)
- contains both whole words `tomato` and `paste` (in any order)
- contains the whole word `passata`
- contains the whole word `pesto`

Products are excluded when the title contains the whole word `fresh`, when they match the configured ignored-brand list, when their titles identify cooking utensils or decorative furniture, or when the retailer reports them as out of stock.

It records product-name, current-price, pack-size, primary-image and **Online Only** status changes, plus newly listed matching products. A new flavour with a new SKU is reported as a **New product**; a flavour rename on an existing SKU is reported as **Name changed**. This avoids guessing whether marketing text represents a flavour. Online-only prices remain in the report and are visibly flagged.

Each weekly report contains one row per changed SKU. When several fields change together, their labels are combined in the single `Change` cell. Before, after and image columns are intentionally omitted; product names remain linked to the retailer source page.

Current price, original price, promotional price and percentage discount have separate columns. Original/promotional/discount fields are populated only when the retailer explicitly identifies a promotion and the original price is greater than the promotional price.

`Temporarily unavailable` products are shown once when they first enter that state, suppressed on subsequent runs, and shown again as `Back in stock` after availability returns. Other out-of-stock products are excluded.

Pricing requests for both retailers are fixed to the online delivery context for **Cheltenham VIC 3192**, configured in `config.json`.

The first successful run emails the complete baseline once. Later runs send an email only when at least one new, previously unreported change exists. Product names in the HTML email and Excel workbook link to their Coles product pages. No-change runs send nothing. Removed or temporarily unavailable products are deliberately not reported because the requested change types do not include removals.

## Schedule

The workflow runs at `20:00 UTC Tuesday`, which is **06:00 AEST Wednesday**. Because AEST is a fixed UTC+10 offset, this is 07:00 in Sydney when daylight saving (AEDT) applies. GitHub Actions schedules can start a few minutes late under load.

## Required GitHub repository setup

1. Create a private GitHub repository and push this folder as its root.
2. In **Settings → Secrets and variables → Actions**, add:
   - `GMAIL_APP_PASSWORD`: a Google App Password for `liamdwaas@gmail.com` (never use or commit the normal Google password).
   - `COLES_BUILD_ID`: optional fallback containing the current Coles Next.js `buildId`. The monitor first attempts automatic discovery. Add/update this only if a run says Coles blocked discovery.
   - `RETAIL_PROXY_URL`: an Australian residential HTTPS proxy URL, including its provider-issued credentials. This is required on GitHub-hosted runners because Coles rejects GitHub datacenter IPs. Store it only as an Actions secret, for example in the provider's documented `http://user:password@host:port` format.
3. In **Settings → Actions → General → Workflow permissions**, select **Read and write permissions** so the workflow can commit its history.
4. Pushing the initial setup creates and emails the baseline. **Actions → Weekly Coles product monitor → Run workflow** remains available for diagnostics, but a manual run does not resend an existing baseline.

Google App Passwords require 2-Step Verification. If Google Workspace policy blocks App Passwords, use an approved SMTP relay and adapt `send_email` in `coles_monitor/reporting.py`.

## Data integrity behavior

- A run where either retailer is blocked, empty, malformed or incomplete fails without replacing the last good combined snapshot or sending a partial report.
- After a baseline exists, a temporarily blocked retailer retains its last verified records while the other retailer continues normally. The workflow emits a GitHub warning, never interprets the access failure as removals, and retries the retailer on the next scheduled run.
- Coles' flag comes from `pricing.onlineSpecial`/an online promotion label; Woolworths' flag comes from `IsOnlineOnly`. The monitor does not infer this status from price differences.
- Browser-fingerprinted sessions are used for compatibility with the retailers' public storefront data routes; no login, cart or checkout access is used.
- When `RETAIL_PROXY_URL` is present, both retailers use the same Australian proxy so their Cheltenham-context data is fetched consistently. The secret is never logged or written to a snapshot.
- Coles build-ID discovery is automatic. `config.json` also contains a last-known build ID verified from the live homepage on 2026-08-24, used only if homepage discovery is challenged; a stale ID makes the run fail safely rather than emit partial data.
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
