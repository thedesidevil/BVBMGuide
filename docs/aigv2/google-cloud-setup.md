# Google Cloud setup for AIG v2

AIG v2 uses two Google APIs with the key in `GOOGLE_MAPS_API_KEY`: **Places API (New)** (place lookup, hours, status, nearby search) and **Routes API** (walking/transit/drive times).

## Steps (Google Cloud console)

1. Open https://console.cloud.google.com and select the project that owns the key in `.env` (APIs & Services → Credentials → find the key).
2. **Enable the APIs:** APIs & Services → Library → search "Places API (New)" → Enable. Repeat for "Routes API". (The legacy "Places API" is a different product and is not enough.)
3. **Confirm billing:** Billing → check the project is linked to an active billing account. Places/Routes calls fail with `REQUEST_DENIED` without it.
4. **Restrict the key:** Credentials → the key → API restrictions → "Restrict key" → tick only **Places API (New)** and **Routes API** → Save. (Add an application/IP restriction when the Lambda deployment exists.)
5. **Budget alert:** Billing → Budgets & alerts → Create budget → scope: this project → amount **$20 / month** → alert thresholds 50%, 90%, 100% → email to the team.
6. Wait ~5 minutes for changes to propagate, then run a small `start` on a test intake and check the Google line of the cost summary is non-zero and no `REQUEST_DENIED` appears.

## Unit prices used for the cost log

`Settings.google_usd_per_call` (src/aigv2/config.py): Places text search / nearby **$0.035 per call**, Routes **$0.005 per route element**. These are **unconfirmed estimates** — check them against https://developers.google.com/maps/billing-and-pricing/pricing (SKU tier, Enterprise/Pro fields, free monthly caps) and update `config.py` if they differ. Directions/transit calls are counted under `route_element` and may bill at a different SKU.
