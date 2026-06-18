"""
mcp_server.py — RefundAgent MCP Server
SSE transport (/sse)  — for ElevenLabs
REST API (/api/orders, /api/stats) — for Lovable frontend
"""

import os
import sqlite3
from datetime import datetime
from fastmcp import FastMCP
from database import init_db
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from mcp.server.sse import SseServerTransport
import uvicorn

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
    Get all recent orders for a customer_id (up to 5, newest first).
    Call after lookup_customer. Present the list to the customer so they can
    specify which item they want to refund. Use the order_id when calling
    validate_and_process_refund.
    """
    db = get_db()
    rows = db.execute(
        "SELECT * FROM orders WHERE customer_id = ? ORDER BY purchase_date DESC LIMIT 5",
        (customer_id,)
    ).fetchall()
    db.close()

    if not rows:
        return {"found": False, "message": "No orders found for this customer."}

    orders = []
    for row in rows:
        days_since = (datetime.now() - datetime.strptime(row["purchase_date"], "%Y-%m-%d")).days
        orders.append({
            "order_id":            row["order_id"],
            "item_name":           row["item_name"],
            "item_type":           row["item_type"],
            "amount":              row["amount"],
            "purchase_date":       row["purchase_date"],
            "days_since_purchase": days_since,
            "refund_status":       row["refund_status"],
        })

    return {"found": True, "orders": orders}


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
    is_opened    = any(w in reason.lower() for w in ["opened", "open", "used", "unsealed"])

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

    if not is_defective and is_opened:
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


# ── REST API endpoints (for Lovable frontend) ─────────────────────────────

async def api_orders(request: Request):
    db = get_db()
    rows = db.execute("""
        SELECT o.order_id, c.name AS customer_name, c.email,
               o.item_name, o.item_type, o.amount,
               o.purchase_date, o.refund_status
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        ORDER BY o.purchase_date DESC
    """).fetchall()
    db.close()
    return JSONResponse([dict(r) for r in rows])


async def api_stats(request: Request):
    db = get_db()
    total    = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    approved = db.execute("SELECT COUNT(*) FROM orders WHERE refund_status='approved'").fetchone()[0]
    db.close()
    return JSONResponse({
        "total_orders":    total,
        "refund_initiated": approved,
        "orders_active":   total - approved,
        "approval_rate":   round(approved / total * 100) if total else 0,
    })


# ── SSE transport (for ElevenLabs MCP) ───────────────────────────────────

sse = SseServerTransport("/messages/")

async def handle_sse(request: Request):
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp._mcp_server.run(
            streams[0], streams[1],
            mcp._mcp_server.create_initialization_options()
        )


# ── Combined Starlette app ────────────────────────────────────────────────

_app = Starlette(routes=[
    Route("/api/orders", api_orders),
    Route("/api/stats",  api_stats),
    Route("/sse",        handle_sse),
    Mount("/messages/",  app=sse.handle_post_message),
])

app = CORSMiddleware(
    _app,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"RefundAgent MCP starting on :{port}")
    print(f"  SSE  → /sse")
    print(f"  REST → /api/orders  /api/stats")
    uvicorn.run(app, host="0.0.0.0", port=port)
