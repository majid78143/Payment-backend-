"""
Razorpay E-Commerce Backend — Flask
=====================================
Run:
    pip install -r requirements.txt
    python app.py

Env vars required:
    DATABASE_URL          — PostgreSQL connection string
    RAZORPAY_KEY_ID       — from Razorpay Dashboard → Settings → API Keys
    RAZORPAY_KEY_SECRET   — from Razorpay Dashboard → Settings → API Keys
    RAZORPAY_WEBHOOK_SECRET — from Razorpay Dashboard → Webhooks → Secret
    PORT                  — (optional) defaults to 5000
"""

import os
import hmac
import hashlib
import time

import razorpay
import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

# ---------------------------------------------------------------------------
# Razorpay client
# ---------------------------------------------------------------------------
razorpay_client = razorpay.Client(
    auth=(
        os.environ.get("RAZORPAY_KEY_ID", ""),
        os.environ.get("RAZORPAY_KEY_SECRET", ""),
    )
)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(url)


def init_db():
    """Create tables if they don't exist, seed sample products."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR(255) NOT NULL,
            description TEXT,
            price       INTEGER NOT NULL,   -- paise (₹1 = 100 paise)
            image_url   TEXT,
            in_stock    BOOLEAN DEFAULT TRUE,
            created_at  TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id                VARCHAR(255) PRIMARY KEY,  -- Razorpay order_id
            product_id        INTEGER REFERENCES products(id),
            amount            INTEGER NOT NULL,
            currency          VARCHAR(10)  DEFAULT 'INR',
            status            VARCHAR(50)  DEFAULT 'created',
            customer_name     VARCHAR(255),
            customer_email    VARCHAR(255),
            customer_phone    VARCHAR(20),
            created_at        TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id                   SERIAL PRIMARY KEY,
            order_id             VARCHAR(255) REFERENCES orders(id),
            razorpay_payment_id  VARCHAR(255) UNIQUE NOT NULL,
            razorpay_signature   VARCHAR(512),
            status               VARCHAR(50) DEFAULT 'captured',
            created_at           TIMESTAMP DEFAULT NOW()
        )
    """)

    # Seed sample products only when table is empty
    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        sample = [
            ("Wireless Headphones", "Premium noise-cancelling headphones", 299900,
             "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=400"),
            ("Mechanical Keyboard", "RGB backlit TKL mechanical keyboard", 499900,
             "https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=400"),
            ("Smart Watch", "Fitness tracker with heart rate monitor", 699900,
             "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=400"),
            ("USB-C Hub", "7-in-1 multiport adapter for laptop", 199900,
             "https://images.unsplash.com/photo-1625842268584-8f3296236761?w=400"),
            ("HD Webcam", "1080p streaming webcam with built-in mic", 349900,
             "https://images.unsplash.com/photo-1587202372775-e229f172b9d7?w=400"),
            ("Phone Stand", "Adjustable aluminium desk phone mount", 89900,
             "https://images.unsplash.com/photo-1586953208448-b95a79798f07?w=400"),
        ]
        for name, desc, price, img in sample:
            cur.execute(
                "INSERT INTO products (name, description, price, image_url) VALUES (%s,%s,%s,%s)",
                (name, desc, price, img),
            )

    conn.commit()
    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/admin")
def admin():
    return send_from_directory("static", "admin.html")

@app.route("/orders")
def orders_page():
    return send_from_directory("static", "orders.html")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.route("/api/healthz")
def healthz():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@app.route("/api/products", methods=["GET"])
def get_products():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM products ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return jsonify(rows)


@app.route("/api/products/<int:pid>", methods=["GET"])
def get_product(pid):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM products WHERE id=%s", (pid,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(row))


@app.route("/api/products", methods=["POST"])
def create_product():
    data = request.json or {}
    if not data.get("name") or not data.get("price"):
        return jsonify({"error": "name and price are required"}), 400
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "INSERT INTO products (name, description, price, image_url) VALUES (%s,%s,%s,%s) RETURNING *",
        (data["name"], data.get("description",""), int(data["price"]), data.get("image_url","")),
    )
    product = dict(cur.fetchone())
    conn.commit(); cur.close(); conn.close()
    return jsonify(product), 201


@app.route("/api/products/<int:pid>", methods=["DELETE"])
def delete_product(pid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id=%s", (pid,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Payments — Step 1: Create Razorpay order
# ---------------------------------------------------------------------------

@app.route("/api/payment/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    amount = data.get("amount")   # paise
    if not amount:
        return jsonify({"error": "amount is required"}), 400

    rz_order = razorpay_client.order.create({
        "amount": int(amount),
        "currency": "INR",
        "receipt": f"rcpt_{int(time.time())}",
        "payment_capture": 1,
    })

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO orders
               (id, product_id, amount, currency, status,
                customer_name, customer_email, customer_phone)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            rz_order["id"],
            data.get("product_id"),
            int(amount),
            "INR",
            "created",
            data.get("customer_name",""),
            data.get("customer_email",""),
            data.get("customer_phone",""),
        ),
    )
    conn.commit(); cur.close(); conn.close()

    return jsonify({
        "order_id": rz_order["id"],
        "amount":   rz_order["amount"],
        "currency": rz_order["currency"],
        "key":      os.environ.get("RAZORPAY_KEY_ID",""),
    })


# ---------------------------------------------------------------------------
# Payments — Step 2: Verify signature after checkout
# ---------------------------------------------------------------------------

@app.route("/api/payment/verify", methods=["POST"])
def verify_payment():
    data = request.json or {}
    rz_order_id   = data.get("razorpay_order_id","")
    rz_payment_id = data.get("razorpay_payment_id","")
    rz_signature  = data.get("razorpay_signature","")

    secret  = os.environ.get("RAZORPAY_KEY_SECRET","")
    msg     = f"{rz_order_id}|{rz_payment_id}"
    expected = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, rz_signature):
        return jsonify({"success": False, "error": "Signature mismatch"}), 400

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("UPDATE orders SET status='paid' WHERE id=%s", (rz_order_id,))
    cur.execute(
        """INSERT INTO payments (order_id, razorpay_payment_id, razorpay_signature, status)
           VALUES (%s,%s,%s,%s)
           ON CONFLICT (razorpay_payment_id) DO NOTHING""",
        (rz_order_id, rz_payment_id, rz_signature, "captured"),
    )
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True, "payment_id": rz_payment_id})


# ---------------------------------------------------------------------------
# Payments — Razorpay Webhook (automatic server-to-server verification)
# ---------------------------------------------------------------------------

@app.route("/api/payment/webhook", methods=["POST"])
def webhook():
    secret    = os.environ.get("RAZORPAY_WEBHOOK_SECRET","")
    signature = request.headers.get("X-Razorpay-Signature","")
    raw_body  = request.get_data()

    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return jsonify({"error": "Invalid signature"}), 400

    event = request.get_json(force=True) or {}
    if event.get("event") == "payment.captured":
        entity    = event["payload"]["payment"]["entity"]
        order_id  = entity.get("order_id")
        pay_id    = entity.get("id")
        if order_id:
            conn = get_db()
            cur  = conn.cursor()
            cur.execute("UPDATE orders SET status='paid' WHERE id=%s", (order_id,))
            cur.execute(
                """INSERT INTO payments (order_id, razorpay_payment_id, status)
                   VALUES (%s,%s,%s) ON CONFLICT (razorpay_payment_id) DO NOTHING""",
                (order_id, pay_id, "captured"),
            )
            conn.commit(); cur.close(); conn.close()

    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@app.route("/api/orders", methods=["GET"])
def get_orders():
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT o.*, p.name AS product_name, p.image_url AS product_image
        FROM orders o
        LEFT JOIN products p ON o.product_id = p.id
        ORDER BY o.created_at DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return jsonify(rows)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/api/dashboard/summary", methods=["GET"])
def dashboard_summary():
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT COUNT(*) cnt, COALESCE(SUM(amount),0) rev FROM orders WHERE status='paid'")
    paid = dict(cur.fetchone())
    cur.execute("SELECT COUNT(*) cnt FROM orders")
    tot  = dict(cur.fetchone())
    cur.execute("SELECT COUNT(*) cnt FROM products")
    prods = dict(cur.fetchone())
    cur.execute("""
        SELECT o.*, p.name AS product_name
        FROM orders o LEFT JOIN products p ON o.product_id=p.id
        ORDER BY o.created_at DESC LIMIT 5
    """)
    recent = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()

    return jsonify({
        "paid_orders":          paid["cnt"],
        "total_revenue_paise":  paid["rev"],
        "total_orders":         tot["cnt"],
        "total_products":       prods["cnt"],
        "recent_orders":        recent,
    })


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
