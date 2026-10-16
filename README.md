# RoomLedger

Roommate expense sharing & monthly settlement web app for Rajat, Solai, and Jogeswara.

## Run locally

```
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 in your browser. Data is stored in `roomledger.db` (SQLite), created automatically on first run.

## Features

- Log expenses under Rent, Food, and Things & Utilities, tagged with who paid.
- Dashboard per calendar month: total spend, category breakdown, individual net balances.
- Automatic optimal "who owes whom" settlement (minimum number of transfers).
- One-click WhatsApp-ready report (group summary + individual statements) with copy buttons.
- "Settle Up Month" locks a month (no more edits) and rolls you into the next month; a locked month can be reopened if needed.
- History page listing all months with totals and settled status.

## Deploying online

This is a standard Flask app, so it can be deployed to any Python host, e.g. Render, Railway, PythonAnywhere, or Fly.io:

- Use `gunicorn app:app` as the start command (add `gunicorn` to requirements.txt for production).
- The SQLite file persists on disk — use a host with a persistent volume (Render/Fly disks, Railway volumes) so data survives restarts.
