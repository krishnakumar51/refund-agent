"""
database.py — SQLite setup + 15 mock CRM profiles
Run once: python database.py
"""

import sqlite3
from datetime import datetime, timedelta

DB = "crm.db"


def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id     TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            email           TEXT UNIQUE NOT NULL,
            phone           TEXT,
            last_refund_date TEXT
        );

        CREATE TABLE IF NOT EXISTS orders (
            order_id        TEXT PRIMARY KEY,
            customer_id     TEXT NOT NULL,
            item_name       TEXT NOT NULL,
            item_type       TEXT NOT NULL CHECK(item_type IN ('physical','digital')),
            amount          REAL NOT NULL,
            purchase_date   TEXT NOT NULL,
            is_opened       INTEGER NOT NULL DEFAULT 0,
            refund_status   TEXT DEFAULT 'none',
            FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
        );
    """)

    # ── 15 mock customers ────────────────────────────────────────────────────
    today = datetime.now()

    customers = [
        # (customer_id, name, email, phone, last_refund_date)
        ("C001", "Alice Johnson",   "alice@example.com",   "+1-555-0101", None),
        ("C002", "Bob Smith",       "bob@example.com",     "+1-555-0102", None),
        ("C003", "Carol White",     "carol@example.com",   "+1-555-0103", (today - timedelta(days=200)).strftime("%Y-%m-%d")),
        ("C004", "David Brown",     "david@example.com",   "+1-555-0104", None),
        ("C005", "Eva Martinez",    "eva@example.com",     "+1-555-0105", (today - timedelta(days=30)).strftime("%Y-%m-%d")),  # recent refund
        ("C006", "Frank Lee",       "frank@example.com",   "+1-555-0106", None),
        ("C007", "Grace Kim",       "grace@example.com",   "+1-555-0107", None),
        ("C008", "Henry Davis",     "henry@example.com",   "+1-555-0108", None),
        ("C009", "Isla Wilson",     "isla@example.com",    "+1-555-0109", (today - timedelta(days=400)).strftime("%Y-%m-%d")),
        ("C010", "James Taylor",    "james@example.com",   "+1-555-0110", None),
        ("C011", "Karen Anderson",  "karen@example.com",   "+1-555-0111", None),
        ("C012", "Liam Thomas",     "liam@example.com",    "+1-555-0112", None),
        ("C013", "Mia Jackson",     "mia@example.com",     "+1-555-0113", None),
        ("C014", "Noah Harris",     "noah@example.com",    "+1-555-0114", None),
        ("C015", "Olivia Clark",    "olivia@example.com",  "+1-555-0115", None),
    ]

    # ── 15 mock orders ───────────────────────────────────────────────────────
    orders = [
        # (order_id, customer_id, item_name, item_type, amount, purchase_date, is_opened)

        # Normal refund eligible (within 30 days, physical, unopened)
        ("ORD-001", "C001", "Wireless Headphones",     "physical", 89.99,  (today - timedelta(days=10)).strftime("%Y-%m-%d"), 0),

        # Defective item — eligible regardless
        ("ORD-002", "C002", "Laptop Stand",            "physical", 45.00,  (today - timedelta(days=20)).strftime("%Y-%m-%d"), 1),

        # Opened, change of mind — DENY
        ("ORD-003", "C003", "Bluetooth Speaker",       "physical", 120.00, (today - timedelta(days=15)).strftime("%Y-%m-%d"), 1),

        # Outside 30-day window — DENY
        ("ORD-004", "C004", "Mechanical Keyboard",     "physical", 175.00, (today - timedelta(days=45)).strftime("%Y-%m-%d"), 0),

        # Recent refund (within 6 months) — DENY
        ("ORD-005", "C005", "USB-C Hub",               "physical", 35.00,  (today - timedelta(days=5)).strftime("%Y-%m-%d"),  0),

        # Digital product — DENY always
        ("ORD-006", "C006", "Adobe Photoshop License", "digital",  299.00, (today - timedelta(days=3)).strftime("%Y-%m-%d"),  0),

        # Normal eligible
        ("ORD-007", "C007", "Ergonomic Mouse",         "physical", 59.99,  (today - timedelta(days=8)).strftime("%Y-%m-%d"),  0),

        # Defective — eligible
        ("ORD-008", "C008", "Smart Watch",             "physical", 249.00, (today - timedelta(days=12)).strftime("%Y-%m-%d"), 1),

        # Old refund history (>6 months) — eligible
        ("ORD-009", "C009", "Desk Lamp",               "physical", 42.00,  (today - timedelta(days=18)).strftime("%Y-%m-%d"), 0),

        # Digital — DENY
        ("ORD-010", "C010", "Spotify Premium Annual",  "digital",  99.00,  (today - timedelta(days=7)).strftime("%Y-%m-%d"),  0),

        # Normal eligible
        ("ORD-011", "C011", "Phone Case",              "physical", 19.99,  (today - timedelta(days=25)).strftime("%Y-%m-%d"), 0),

        # Outside window — DENY
        ("ORD-012", "C012", "Standing Desk Mat",       "physical", 65.00,  (today - timedelta(days=60)).strftime("%Y-%m-%d"), 0),

        # Normal eligible — unopened, within 30 days
        ("ORD-013", "C013", "Webcam HD 1080p",         "physical", 79.99,  (today - timedelta(days=3)).strftime("%Y-%m-%d"),  0),

        # Opened change of mind — DENY
        ("ORD-014", "C014", "Gaming Headset",          "physical", 110.00, (today - timedelta(days=22)).strftime("%Y-%m-%d"), 1),

        # Normal eligible
        ("ORD-015", "C015", "Portable Charger",        "physical", 29.99,  (today - timedelta(days=14)).strftime("%Y-%m-%d"), 0),
    ]

    c.executemany(
        "INSERT OR IGNORE INTO customers VALUES (?,?,?,?,?)", customers
    )
    c.executemany(
        "INSERT OR IGNORE INTO orders VALUES (?,?,?,?,?,?,?,?)",
        [(o[0],o[1],o[2],o[3],o[4],o[5],o[6],'none') for o in orders]
    )

    conn.commit()
    conn.close()
    print(f"Database initialised: {DB}")
    print(f"  {len(customers)} customers")
    print(f"  {len(orders)} orders")


if __name__ == "__main__":
    init_db()
