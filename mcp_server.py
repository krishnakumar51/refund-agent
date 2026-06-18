"""
mcp_server.py — RefundAgent MCP Server
Uses fastmcp v3 directly.

ElevenLabs SSE URL: https://your-domain/sse
Health check:       https://your-domain/
"""

import os
import sqlite3
from datetime import datetime
from fastmcp import FastMCP
from database import init_db

# ── Init DB on startup ────────────────────────────────────────────────────
init_db()

mcp = FastMCP("RefundAgent")

DB = "crm.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


# ── Tool 1 ────────────────────────────────────────────────────────────────

@mcp.tool()
def lookup_customer(email: str) -> dict:
    """
    Look up a customer in the CRM by email address.
    Call this first after the customer provides their email.
    Returns customer_id needed for other tools.
    """
    db = get_db()
    row = db.execute(
        "SELECT * FROM customers WHERE LOWER(email) = LOWER(?)", (email.strip(),)
    ).fetchone()
    db.close()

    if not row:
        return {"found": False, "message": "No account found with that email address."}

    return {
        "found":            True,
        "customer_id":      row["customer_id"],
        "name":             row["name"],
        "email":            row["email"],
        "last_refund_date": row["last_refund_date"],
    }


# ── Tool 2 ────────────────────────────────────────────────────────────────

@mcp.tool()
def get_order_details(customer_id: str) -> dict:
    """
    Get the most recent order for a customer_id.
    Call after lookup_customer. Returns order info needed for refund validation.
    """
    db = get_db()
    row = db.execute(
        "SELECT * FROM orders WHERE customer_id = ? ORDER BY purchase_date DESC LIMIT 1",
        (customer_id,)
    ).fetchone()
    db.close()

    if not row:
        return {"found": False, "message": "No orders found for this customer."}

    days_since = (datetime.now() - datetime.strptime(row["purchase_date"], "%Y-%m-%d")).days

    return {
        "found":               True,
        "order_id":            row["order_id"],
        "item_name":           row["item_name"],
        "item_type":           row["item_type"],
        "amount":              row["amount"],
        "purchase_date":       row["purchase_date"],
        "days_since_purchase": days_since,
        "is_opened":           bool(row["is_opened"]),
        "refund_status":       row["refund_status"],
    }


# ── Tool 3 ────────────────────────────────────────────────────────────────

@mcp.tool()
def validate_and_process_refund(customer_id: str, order_id: str, reason: str) -> dict:
    """
    Validate and process a refund against company policy.
    Policy: 30-day window, no digital goods, max 1 refund per 6 months,
    change-of-mind requires unopened item, defective items always approved.
    Call after confirming order details with the customer.
    """
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
    order    = db.execute("SELECT * FROM orders WHERE order_id = ? AND customer_id = ?",
                          (order_id, customer_id)).fetchone()

    if not customer or not order:
        db.close()
        return {"approved": False, "reason": "Customer or order not found."}

    if order["refund_status"] == "approved":
        db.close()
        return {"approved": False, "reason": "A refund has already been processed for this order."}

    days_since   = (datetime.now() - datetime.strptime(order["purchase_date"], "%Y-%m-%d")).days
    is_defective = any(w in reason.lower() for w in
                       ["defect", "broken", "damage", "faulty", "not working", "dead on arrival"])

    if order["item_type"] == "digital":
        db.close()
        return {"approved": False, "reason": "Digital products are non-refundable per our policy."}

    if days_since > 30:
        db.close()
        return {"approved": False,
                "reason": f"Order is {days_since} days old. Refunds are only accepted within 30 days."}

    if customer["last_refund_date"]:
        days_since_refund = (datetime.now() - datetime.strptime(
            customer["last_refund_date"], "%Y-%m-%d")).days
        if days_since_refund < 180:
            db.close()
            return {"approved": False,
                    "reason": "Account received a refund in the past 6 months. Limit is one per 6 months."}

    if not is_defective and order["is_opened"]:
        db.close()
        return {"approved": False,
                "reason": "Change of mind refunds require the item to be unopened and in original condition."}

    # ── Approve ───────────────────────────────────────────────────────────
    db.execute("UPDATE orders SET refund_status = 'approved' WHERE order_id = ?", (order_id,))
    db.execute("UPDATE customers SET last_refund_date = ? WHERE customer_id = ?",
               (datetime.now().strftime("%Y-%m-%d"), customer_id))
    db.commit()
    db.close()

    return {
        "approved": True,
        "amount":   order["amount"],
        "message":  f"Refund of ${order['amount']:.2f} approved for {order['item_name']}. "
                    "Funds will be returned within 5–7 business days.",
    }


# ── Run ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"RefundAgent MCP starting on port {port}")
    print(f"SSE endpoint: /sse")
    mcp.run(transport="sse", host="0.0.0.0", port=port)
