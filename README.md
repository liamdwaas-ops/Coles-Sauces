# Coles product change monitor

This repository checks Coles once a week for products whose **name** matches one of these rules:

- contains both whole words `pasta` and `sauce` (in any order)
- contains both whole words `tomato` and `paste` (in any order)
- contains the whole word `pesto`
- contains the whole word `passata`

It records product-name, current-price, pack-size and primary-image changes, plus newly listed matching products. A new flavour with a new SKU is reported as a **New product**; a flavour rename on an existing SKU is reported as **Name changed**. This avoids guessing whether marketing text represents a flavour.

Pricing is fixed to the Coles delivery context for **Cheltenham VIC 3192**, configured in `config.json`.

The first successful run creates a silent baseline. Later runs send an email only when at least one new, previously unreported change exists. Product names in the HTML email and Excel history link to their Coles product pages. No-change runs send nothing. Removed or temporarily unavailable products are deliberately not reported because the requested change types do not include removals.

## Schedule

The workflow runs at `20:00 UTC Tuesday`, which is **06:00 AEST Wednesday**. Because AEST is a fixed UTC+10 offset, this is 07:00 in Sydney when daylight saving (AEDT) applies. GitHub Actions schedules can start a few minutes late under load.

## Required GitHub repository setup

1. Create a private GitHub repository and push this folder as its root.
2. In **Settings → Secrets and variables → Actions**, add:
   - `GMAIL_APP_PASSWORD`: a Google App Password for `liamdwaas@gmail.com` (never use or commit the normal Google password).
   - `COLES_BUILD_ID`: optional fallback containing the current Coles Next.js `buildId`. The monitor first attempts automatic discovery. Add/update this only if a run says Coles blocked discovery.
3. In **Settings → Actions → General → Workflow permissions**, select **Read and write permissions** so the workflow can commit its history.
4. In **Actions → Weekly Coles product monitor**, choose **Run workflow** once. The first successful run is the silent baseline.

Google App Passwords require 2-Step Verification. If Google Workspace policy blocks App Passwords, use an approved SMTP relay and adapt `send_email` in `coles_monitor/reporting.py`.

## Data integrity behavior

- A run that is blocked, empty, malformed or incomplete fails without replacing the last good snapshot.
- Change events have deterministic IDs and are stored in `data/events.json`, preventing duplicate reports.
- The complete audit history is kept in `data/coles-product-change-history.xlsx` and uploaded as a workflow artifact.
- Every search includes postcode `3192`, state `VIC` and delivery context. Prices should be treated as Coles online prices for that location, not as a claim about shelf prices at an unspecified physical store.

## Local test

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python run_monitor.py --fixture tests/fixtures/week1.json --no-email
python run_monitor.py --fixture tests/fixtures/week2.json --no-email
```

The fixture names and URLs use the reserved `example.test` domain and are tests only; they are not Coles product claims.
