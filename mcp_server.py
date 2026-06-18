"""
mcp_server.py — MCP server for the Refund Agent
Exposes 3 tools that ElevenLabs calls via SSE connection.

Run:
    python mcp_server.py

Then in ElevenLabs:
    Server type: SSE
    URL: http://localhost:8000/sse   (or your ngrok URL)
"""

import sqlite3
from datetime import datetime
from mcp.server.fastmcp import FastMCP

DB = "crm.db"

mcp = FastMCP("RefundAgent")


# ── DB helper ─────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


# ── Tool 1: lookup_customer ───────────────────────────────────────────────

@mcp.tool()
def lookup_customer(email: str) -> dict:
    """
    Look up a customer in the CRM by their email address.
    Always call this first after the customer provides their email.
    Returns customer profile including customer_id needed for other tools.
    """
    db = get_db()
    row = db.execute(
        "SELECT * FROM customers WHERE LOWER(email) = LOWER(?)", (email.strip(),)
    ).fetchone()
    db.close()

    if not row:
        return {
            "found": False,
            "message": "No account found with that email address. Please check and try again."
        }

    return {
        "found": True,
        "customer_id": row["customer_id"],
        "name": row["name"],
        "email": row["email"],
        "last_refund_date": row["last_refund_date"]
    }


# ── Tool 2: get_order_details ─────────────────────────────────────────────

@mcp.tool()
def get_order_details(customer_id: str) -> dict:
    """
    Retrieve the most recent order for a given customer_id.
    Call this after lookup_customer to get order info needed for refund validation.
    Returns order details including purchase date, item type, amount, and whether item is opened.
    """
    db = get_db()
    row = db.execute(
        "SELECT * FROM orders WHERE customer_id = ? ORDER BY purchase_date DESC LIMIT 1",
        (customer_id,)
    ).fetchone()
    db.close()

    if not row:
        return {
            "found": False,
            "message": "No orders found for this customer."
        }

    purchase_date = datetime.strptime(row["purchase_date"], "%Y-%m-%d")
    days_since = (datetime.now() - purchase_date).days

    return {
        "found": True,
        "order_id":           row["order_id"],
        "item_name":          row["item_name"],
        "item_type":          row["item_type"],       # "physical" or "digital"
        "amount":             row["amount"],
        "purchase_date":      row["purchase_date"],
        "days_since_purchase": days_since,
        "is_opened":          bool(row["is_opened"]),
        "refund_status":      row["refund_status"]
    }


# ── Tool 3: validate_and_process_refund ──────────────────────────────────

@mcp.tool()
def validate_and_process_refund(customer_id: str, order_id: str, reason: str) -> dict:
    """
    Validate the refund request against company policy and process it if eligible.
    Call this after confirming order details with the customer.

    Policy rules enforced:
    - Refund window: 30 days from purchase
    - Digital goods: never refundable
    - Max 1 refund per 6 months per customer
    - Change of mind: item must be unopened
    - Defective/damaged: always approved regardless of opened status

    Returns approval status, reason, and refund amount if approved.
    """
    db = get_db()

    customer = db.execute(
        "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()

    order = db.execute(
        "SELECT * FROM orders WHERE order_id = ? AND customer_id = ?",
        (order_id, customer_id)
    ).fetchone()

    if not customer or not order:
        db.close()
        return {"approved": False, "reason": "Customer or order not found."}

    if order["refund_status"] == "approved":
        db.close()
        return {"approved": False, "reason": "A refund has already been processed for this order."}

    purchase_date = datetime.strptime(order["purchase_date"], "%Y-%m-%d")
    days_since    = (datetime.now() - purchase_date).days
    reason_lower  = reason.lower()
    is_defective  = any(w in reason_lower for w in ["defect", "broken", "damage", "faulty", "not working", "dead on arrival"])

    # ── Rule 1: Digital goods ─────────────────────────────────────────────
    if order["item_type"] == "digital":
        db.close()
        return {
            "approved": False,
            "reason": "Digital products and software licenses are non-refundable per our policy."
        }

    # ── Rule 2: 30-day window ─────────────────────────────────────────────
    if days_since > 30:
        db.close()
        return {
            "approved": False,
            "reason": f"This order was placed {days_since} days ago. Our refund policy only covers purchases within 30 days."
        }

    # ── Rule 3: 6-month refund frequency limit ────────────────────────────
    if customer["last_refund_date"]:
        last = datetime.strptime(customer["last_refund_date"], "%Y-%m-%d")
        if (datetime.now() - last).days < 180:
            db.close()
            return {
                "approved": False,
                "reason": "Your account has already received a refund in the past 6 months. Only one refund per 6 months is permitted."
            }

    # ── Rule 4: Change of mind — must be unopened ─────────────────────────
    if not is_defective and order["is_opened"]:
        db.close()
        return {
            "approved": False,
            "reason": "Change of mind refunds require the item to be in its original, unopened condition."
        }

    # ── All checks passed: APPROVE ────────────────────────────────────────
    db.execute(
        "UPDATE orders SET refund_status = 'approved' WHERE order_id = ?",
        (order_id,)
    )
    db.execute(
        "UPDATE customers SET last_refund_date = ? WHERE customer_id = ?",
        (datetime.now().strftime("%Y-%m-%d"), customer_id)
    )
    db.commit()
    db.close()

    return {
        "approved": True,
        "amount":   order["amount"],
        "message":  f"Refund of ${order['amount']:.2f} approved for {order['item_name']}. "
                    f"Funds will be returned to your original payment method within 5–7 business days."
    }


# ── Run ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting RefundAgent MCP server on http://localhost:8000/sse")
    print("Paste this URL into ElevenLabs > Tools > MCP > Server URL")
    mcp.run(transport="sse")
