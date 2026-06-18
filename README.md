# ShopEasy Refund Agent — MCP Server

AI-powered refund processing backend for the ShopEasy Customer Support Agent. Built with FastMCP, deployed on Railway, and connected to ElevenLabs Conversational AI via SSE transport.

## Architecture

```
ElevenLabs Voice Agent
        │
        │  SSE (Model Context Protocol)
        ▼
FastMCP Server (Railway)
        │
        ├── lookup_customer
        ├── get_order_details
        └── validate_and_process_refund
        │
        ▼
   SQLite CRM (crm.db)
        │
        ▼
REST API (/api/orders, /api/stats)
        │
        ▼
  Lovable Frontend (Vercel)
```

The server runs a single process handling both MCP (SSE transport for ElevenLabs) and REST (JSON endpoints for the frontend) on the same Railway port using a combined Starlette ASGI app.

## MCP Tools

### `lookup_customer(email: str)`
Looks up a customer by email (case-insensitive). Called first in every refund flow after the customer provides their email. Returns `customer_id`, name, email, and `last_refund_date`.

### `get_order_details(customer_id: str)`
Returns up to 5 most recent orders for a customer (newest first). Each order includes `order_id`, `item_name`, `item_type`, `amount`, `purchase_date`, `days_since_purchase`, and `refund_status`.

### `validate_and_process_refund(customer_id: str, order_id: str, reason: str)`
Enforces refund policy in code and updates the database on approval.

| Rule | Detail |
|------|--------|
| Time window | Refunds only within 30 days of purchase |
| Digital goods | Non-refundable, no exceptions |
| Refund frequency | Max 1 refund per 6 months per account |
| Opened items | Change-of-mind refunds require item to be unopened |
| Defective items | Always approved regardless of other conditions |

`is_opened` is inferred from the customer's stated reason (keywords: "opened", "used", "unsealed") — not stored in the database. The agent asks the customer directly during the conversation.

## REST API Endpoints

These endpoints serve the admin CRM frontend.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/orders` | GET | All orders joined with customer name/email, newest first |
| `/api/stats` | GET | `total_orders`, `refund_initiated`, `orders_active`, `approval_rate` |
| `/sse` | GET | MCP SSE transport endpoint (for ElevenLabs) |

All endpoints include CORS headers (`allow_origins=["*"]`).

## Database

SQLite (`crm.db`) with two tables, auto-seeded on first run:

**customers** — 15 mock profiles (C001–C015)

**orders** — 19 mock orders (ORD-001–ORD-019) across physical and digital items

Purchase dates are set relative to today at startup, so the 30-day policy window stays realistic on every redeploy.

Interesting test cases in the mock data:
- **ORD-004** (David, Mechanical Keyboard) — 45 days old → denied, outside 30-day window
- **ORD-006** (Frank, Adobe Photoshop License) — digital good → always denied
- **C005** (Eva) — refunded 30 days ago → denied, 6-month limit not cleared
- **ORD-001/ORD-016** (Alice) — two active physical orders, both eligible → good demo

## Tech Stack

| Component | Technology |
|-----------|------------|
| MCP framework | FastMCP v3.4.2 |
| ASGI server | Uvicorn |
| HTTP routing | Starlette |
| Database | SQLite |
| MCP transport | SSE (`mcp.server.sse.SseServerTransport`) |
| Hosting | Railway |

**Why SSE and not `mcp.http_app()`?** ElevenLabs uses the SSE MCP protocol. FastMCP's `http_app()` creates a StreamableHTTP server (a different protocol) which returns 404 at `/sse`. The fix is to use `SseServerTransport` directly with a custom Starlette app, bypassing `mcp.run()`.

## Project Structure

```
refund-agent/
├── mcp_server.py      # MCP tools + REST endpoints + combined ASGI app
├── database.py        # DB schema + mock data seeding
├── requirements.txt
├── Procfile           # Railway: web: python mcp_server.py
└── crm.db             # SQLite (auto-created on first run)
```

## Local Setup

```bash
git clone https://github.com/[your-username]/refund-agent
cd refund-agent
pip install -r requirements.txt
python mcp_server.py
# SSE:    http://localhost:8000/sse
# Orders: http://localhost:8000/api/orders
# Stats:  http://localhost:8000/api/stats
```

## Railway Deployment

1. Connect GitHub repo to Railway
2. Set env var: `PORT=8000`
3. Set public networking target port to `8000` (must match PORT)
4. Procfile handles startup: `web: python mcp_server.py`

> PORT env var and Railway public networking target port must match — mismatch causes 502 errors.

## ElevenLabs Configuration

- MCP tool → SSE URL: `https://refund-agent-production.up.railway.app/sse`
- LLM: GPT-4o (Gemini models hallucinate fake orders instead of calling tools)
- Knowledge Base: refund policy document for agent tone/explanations
- System prompt enforces strict sequencing and email normalization (spoken "alice at example dot com" → `alice@example.com`)

## Key Design Decisions

**Policy enforced in code, not prompt.** All business rules live in `validate_and_process_refund`. The agent cannot override policy through conversation — denial reasons come from the tool response, not the LLM.

**Email normalization in tool parameter description.** STT transcribes spoken emails literally. The conversion instruction sits in the tool's parameter description so the LLM normalizes before calling.

**Single port, dual protocol.** Railway exposes one public port. SSE (ElevenLabs) and REST (frontend) share it via Starlette routing — REST routes registered first so they take priority.
