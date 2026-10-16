# RoomLedger

Roommate expense sharing & monthly settlement web app for Rajat, Solai, and Jogeswara.

**Live app:** https://roomledger-ochre.vercel.app

## Run locally

Requires a Postgres database (the app uses Postgres everywhere, including locally, so dev matches production). Easiest path: use the same Neon database Vercel provisioned.

```
pip install -r requirements.txt
vercel env pull .env.local   # pulls DATABASE_URL from the linked Vercel project
set -a; source .env.local; set +a   # or just export DATABASE_URL=... manually
python app.py
```

Open http://127.0.0.1:5000.

## Features

- Log expenses under Rent, Food, and Things & Utilities, tagged with who paid.
- Dashboard per calendar month: total spend, category breakdown, individual net balances.
- Automatic optimal "who owes whom" settlement (minimum number of transfers).
- One-click WhatsApp-ready report (group summary + individual statements) with copy buttons.
- "Settle Up Month" locks a month (no more edits) and rolls you into the next month; a locked month can be reopened if needed.
- History page listing all months with totals and settled status.
- CSV export and demo data seeding per month.

## Deployment (Vercel)

Deployed as Python serverless functions (`api/index.py` wraps the Flask `app`, routed via `vercel.json`) with a **Neon Postgres** database (added via the Vercel Postgres/Neon marketplace integration, resource name `roomledger-db`) for persistent storage — Vercel's filesystem is ephemeral, so local SQLite wouldn't survive across requests.

To redeploy after changes:

```
git push                 # if the GitHub integration auto-deploys
# or
npx vercel deploy --prod
```

`DATABASE_URL` is already configured as a project environment variable in Vercel (production/preview/development) — no manual setup needed for new deployments.
