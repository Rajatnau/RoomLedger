import csv
import io
import os
from calendar import month_name
from datetime import date, datetime

import psycopg2
import psycopg2.extras
from flask import Flask, Response, g, redirect, render_template, request, url_for

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL (or POSTGRES_URL) environment variable is required. "
        "Set it to your Postgres/Neon/Vercel Postgres connection string."
    )

ROOMMATES = ["Rajat", "Solai", "Jogeswara"]
SELF = "Rajat"
CATEGORIES = [
    "Food",
    "Electricity Bill",
    "Water Bill",
    "Household Items",
    "Travel",
    "Utilities and Other Expenses",
]

ROOMMATE_STYLE = {
    "Rajat": {"bg": "bg-indigo-600", "bg_light": "bg-indigo-50", "text": "text-indigo-700",
              "border": "border-indigo-200", "initial": "R"},
    "Solai": {"bg": "bg-rose-500", "bg_light": "bg-rose-50", "text": "text-rose-700",
              "border": "border-rose-200", "initial": "S"},
    "Jogeswara": {"bg": "bg-emerald-500", "bg_light": "bg-emerald-50", "text": "text-emerald-700",
                  "border": "border-emerald-200", "initial": "J"},
}

CATEGORY_STYLE = {
    "Food": {"icon": "\U0001F354", "bg": "bg-emerald-100", "text": "text-emerald-700", "bar": "bg-emerald-500"},
    "Electricity Bill": {"icon": "⚡", "bg": "bg-amber-100", "text": "text-amber-700", "bar": "bg-amber-500"},
    "Water Bill": {"icon": "\U0001F4A7", "bg": "bg-sky-100", "text": "text-sky-700", "bar": "bg-sky-500"},
    "Household Items": {"icon": "\U0001F9FA", "bg": "bg-violet-100", "text": "text-violet-700", "bar": "bg-violet-500"},
    "Travel": {"icon": "✈️", "bg": "bg-rose-100", "text": "text-rose-700", "bar": "bg-rose-500"},
    "Utilities and Other Expenses": {"icon": "\U0001F527", "bg": "bg-slate-200", "text": "text-slate-700", "bar": "bg-slate-500"},
}

DEMO_EXPENSES = [
    (1, "Grocery & Rice Provisions", "Food", 3600, "Solai"),
    (5, "October Electricity Bill", "Electricity Bill", 1800, "Rajat"),
    (8, "Water Tanker", "Water Bill", 600, "Jogeswara"),
    (12, "Kitchen Supplies", "Household Items", 1200, "Rajat"),
    (18, "Milk & Vegetables", "Food", 1800, "Jogeswara"),
]

app = Flask(__name__)


def display_name(person):
    return person


app.jinja_env.globals["display_name"] = display_name
app.jinja_env.globals["roommate_style"] = ROOMMATE_STYLE
app.jinja_env.globals["category_style"] = CATEGORY_STYLE


class DB:
    """Thin wrapper so existing sqlite-style db.execute(sql, params) call sites
    work unchanged against psycopg2 (translates '?' placeholders to '%s')."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_db():
    if "db" not in g:
        g.db = DB(psycopg2.connect(DATABASE_URL))
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            month TEXT NOT NULL,
            expense_date TEXT NOT NULL,
            category TEXT NOT NULL,
            amount DOUBLE PRECISION NOT NULL,
            paid_by TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settled_months (
            month TEXT PRIMARY KEY,
            settled_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    cur.close()
    conn.close()


def current_month():
    return date.today().strftime("%Y-%m")


app.jinja_env.globals["current_month"] = current_month


def month_label(month_str):
    d = datetime.strptime(month_str, "%Y-%m")
    return f"{month_name[d.month]} {d.year}"


def shift_month(month_str, delta):
    d = datetime.strptime(month_str, "%Y-%m")
    year = d.year + (d.month - 1 + delta) // 12
    month = (d.month - 1 + delta) % 12 + 1
    return f"{year:04d}-{month:02d}"


def is_settled(db, month):
    row = db.execute(
        "SELECT 1 FROM settled_months WHERE month = ?", (month,)
    ).fetchone()
    return row is not None


def compute_settlement(expenses):
    total = sum(e["amount"] for e in expenses)
    share = total / len(ROOMMATES) if expenses else 0.0

    category_totals = {c: 0.0 for c in CATEGORIES}
    paid_totals = {p: 0.0 for p in ROOMMATES}
    for e in expenses:
        category_totals[e["category"]] = category_totals.get(e["category"], 0.0) + e["amount"]
        paid_totals[e["paid_by"]] += e["amount"]

    balances = {p: round(paid_totals[p] - share, 2) for p in ROOMMATES}

    debtors = sorted(
        ([-amt, p] for p, amt in balances.items() if amt < -0.01)
    )
    creditors = sorted(
        ([amt, p] for p, amt in balances.items() if amt > 0.01), reverse=True
    )

    transactions = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        pay = min(debtors[i][0], creditors[j][0])
        if pay > 0.01:
            transactions.append(
                {"from": debtors[i][1], "to": creditors[j][1], "amount": round(pay, 2)}
            )
        debtors[i][0] -= pay
        creditors[j][0] -= pay
        if debtors[i][0] <= 0.01:
            i += 1
        if creditors[j][0] <= 0.01:
            j += 1

    # Step A: raw, un-netted per-payer debts (each ower owes payer exactly 1/3 of what the payer spent)
    raw_debts = {}
    for payer in ROOMMATES:
        raw_debts[payer] = [
            {"from": other, "amount": round(paid_totals[payer] / len(ROOMMATES), 2)}
            for other in ROOMMATES
            if other != payer
        ]

    category_pct = {
        c: (round(category_totals[c] / total * 100) if total > 0 else 0) for c in CATEGORIES
    }

    return {
        "total": round(total, 2),
        "share": round(share, 2),
        "category_totals": category_totals,
        "category_pct": category_pct,
        "paid_totals": paid_totals,
        "balances": balances,
        "transactions": transactions,
        "raw_debts": raw_debts,
        "item_count": len(expenses),
    }


@app.route("/")
def home():
    return redirect(url_for("dashboard", month=current_month()))


@app.route("/roommates")
def roommates():
    return render_template("roommates.html", roommates=ROOMMATES)


@app.route("/month/<month>")
def dashboard(month):
    db = get_db()
    expenses = db.execute(
        "SELECT * FROM expenses WHERE month = ? ORDER BY expense_date DESC, id DESC",
        (month,),
    ).fetchall()
    settlement = compute_settlement(expenses)
    settled = is_settled(db, month)

    return render_template(
        "dashboard.html",
        active_tab="dashboard",
        month=month,
        month_label=month_label(month),
        prev_month=shift_month(month, -1),
        next_month=shift_month(month, 1),
        expenses=expenses,
        settlement=settlement,
        settled=settled,
        roommates=ROOMMATES,
        categories=CATEGORIES,
        today=date.today().isoformat(),
    )


@app.route("/month/<month>/expense", methods=["POST"])
def add_expense(month):
    db = get_db()
    if is_settled(db, month):
        return redirect(url_for("dashboard", month=month))

    expense_date = request.form["expense_date"]
    category = request.form["category"]
    amount = float(request.form["amount"])
    paid_by = request.form["paid_by"]
    title = request.form.get("title", "").strip()

    if category not in CATEGORIES or paid_by not in ROOMMATES or amount <= 0 or not title:
        return redirect(url_for("dashboard", month=month))

    db.execute(
        """
        INSERT INTO expenses (month, expense_date, category, amount, paid_by, title, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            month,
            expense_date,
            category,
            amount,
            paid_by,
            title,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    db.commit()
    return redirect(url_for("dashboard", month=month))


@app.route("/month/<month>/expense/<int:expense_id>/delete", methods=["POST"])
def delete_expense(month, expense_id):
    db = get_db()
    if not is_settled(db, month):
        db.execute("DELETE FROM expenses WHERE id = ? AND month = ?", (expense_id, month))
        db.commit()
    return redirect(url_for("dashboard", month=month))


@app.route("/month/<month>/settle", methods=["POST"])
def settle_month(month):
    db = get_db()
    if not is_settled(db, month):
        db.execute(
            "INSERT INTO settled_months (month, settled_at) VALUES (?, ?)",
            (month, datetime.now().isoformat(timespec="seconds")),
        )
        db.commit()
    return redirect(url_for("dashboard", month=month))


@app.route("/month/<month>/reopen", methods=["POST"])
def reopen_month(month):
    db = get_db()
    db.execute("DELETE FROM settled_months WHERE month = ?", (month,))
    db.commit()
    return redirect(url_for("dashboard", month=month))


@app.route("/month/<month>/demo", methods=["POST"])
def load_demo(month):
    db = get_db()
    if not is_settled(db, month):
        for day, title, category, amount, paid_by in DEMO_EXPENSES:
            db.execute(
                """
                INSERT INTO expenses (month, expense_date, category, amount, paid_by, title, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    month,
                    f"{month}-{day:02d}",
                    category,
                    amount,
                    paid_by,
                    title,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
        db.commit()
    return redirect(url_for("dashboard", month=month))


@app.route("/month/<month>/export.csv")
def export_csv(month):
    db = get_db()
    expenses = db.execute(
        "SELECT * FROM expenses WHERE month = ? ORDER BY expense_date", (month,)
    ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Title", "Category", "Paid By", "Amount"])
    for e in expenses:
        writer.writerow([e["expense_date"], e["title"], e["category"], e["paid_by"], e["amount"]])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=roomledger-{month}.csv"},
    )


@app.route("/month/<month>/report")
def report(month):
    db = get_db()
    expenses = db.execute(
        "SELECT * FROM expenses WHERE month = ? ORDER BY expense_date", (month,)
    ).fetchall()
    settlement = compute_settlement(expenses)

    group_lines = [
        "\U0001F4CA ROOMLEDGER SETTLE-UP REPORT",
        f"\U0001F5D3 Period: {month_label(month)}",
        f"\U0001F4B0 Total Room Expense: ₹{settlement['total']:,.0f}",
        f"\U0001F464 Equal Share/Person: ₹{settlement['share']:,.0f}",
        "",
        "\U0001F4C2 Category Breakdown:",
    ]
    for c in CATEGORIES:
        if settlement["category_totals"][c] > 0:
            group_lines.append(f"• {c}: ₹{settlement['category_totals'][c]:,.0f}")
    group_lines += ["", "\U0001F4B3 Paid Upfront:"]
    for p in ROOMMATES:
        group_lines.append(f"• {display_name(p)}: ₹{settlement['paid_totals'][p]:,.0f}")
    group_lines += ["", "\U0001F91D FINAL SETTLEMENT PAYMENTS (Who Owes Whom):"]
    if settlement["transactions"]:
        for idx, t in enumerate(settlement["transactions"], start=1):
            group_lines.append(
                f"{idx}. {display_name(t['from'])} ➡️ pays {display_name(t['to'])}: ₹{t['amount']:,.0f}"
            )
    else:
        group_lines.append("Everyone is already settled up!")
    group_lines += ["", "Please verify and complete payments to settle the month! \U0001F64F"]
    group_text = "\n".join(group_lines)

    individual_texts = {}
    for p in ROOMMATES:
        lines = [
            f"\U0001F464 ROOMLEDGER REPORT FOR {p.upper()}",
            f"\U0001F5D3 Period: {month_label(month)}",
            f"\U0001F4B5 Amount Paid by {p}: ₹{settlement['paid_totals'][p]:,.0f}",
            f"⚖️ {p}'s Fair Share: ₹{settlement['share']:,.0f}",
            "",
            "\U0001F4CC Required Settlement Action:",
        ]
        own_actions = [t for t in settlement["transactions"] if t["from"] == p or t["to"] == p]
        if own_actions:
            for t in own_actions:
                if t["from"] == p:
                    lines.append(f"• {p} ➡️ pays {display_name(t['to'])}: ₹{t['amount']:,.0f}")
                else:
                    lines.append(f"• {display_name(t['from'])} ➡️ pays {p}: ₹{t['amount']:,.0f}")
        else:
            lines.append("• No payment needed — you're settled!")
        lines += ["", "Please check and complete the transfer! \U0001F64F"]
        individual_texts[p] = "\n".join(lines)

    return render_template(
        "report.html",
        active_tab="report",
        month=month,
        month_label=month_label(month),
        group_text=group_text,
        individual_texts=individual_texts,
        roommates=ROOMMATES,
    )


@app.route("/history")
def history():
    db = get_db()
    rows = db.execute(
        "SELECT month, SUM(amount) as total, COUNT(*) as cnt FROM expenses GROUP BY month ORDER BY month DESC"
    ).fetchall()
    settled_months = {
        r["month"] for r in db.execute("SELECT month FROM settled_months").fetchall()
    }
    months = [
        {
            "month": r["month"],
            "label": month_label(r["month"]),
            "total": r["total"],
            "count": r["cnt"],
            "settled": r["month"] in settled_months,
        }
        for r in rows
    ]
    return render_template("history.html", active_tab="history", months=months)


init_db()

if __name__ == "__main__":
    app.run(debug=True)
