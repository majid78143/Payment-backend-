# Razorpay E-Commerce Shop — Self-Hosted

Complete e-commerce backend with Razorpay payment integration.  
**No framework needed on frontend** — pure HTML/CSS/JS, seedha browser mein chalega.

---

## Project Structure

```
razorpay-shop/
├── app.py              ← Flask backend (sabhi API routes)
├── requirements.txt    ← Python dependencies
├── .env.example        ← Environment variables template
├── static/
│   ├── index.html      ← Product listing + checkout
│   ├── orders.html     ← Orders page
│   └── admin.html      ← Admin panel (products + dashboard)
└── README.md
```

---

## Setup Guide

### Step 1 — Python & packages install karo

```bash
pip install -r requirements.txt
```

### Step 2 — PostgreSQL database banao

Local PostgreSQL mein ek database banao:

```sql
CREATE DATABASE shopdb;
```

### Step 3 — Environment variables set karo

`.env.example` copy karo aur fill in karo:

```bash
cp .env.example .env
```

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/shopdb
RAZORPAY_KEY_ID=rzp_live_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your_secret_here
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret_here
PORT=5000
```

> **Razorpay keys kahan milenge?**
> Dashboard → Settings → API Keys → Generate Keys

### Step 4 — App chalao

```bash
# Linux/Mac:
export $(cat .env | xargs) && python app.py

# Windows (PowerShell):
Get-Content .env | ForEach-Object { $k,$v = $_.split('=',2); [System.Environment]::SetEnvironmentVariable($k,$v) }
python app.py
```

App `http://localhost:5000` pe chalega.  
Tables aur sample products **automatically** ban jayenge pehli baar.

---

## Pages

| URL       | Description                   |
|-----------|-------------------------------|
| `/`       | Product listing + checkout    |
| `/orders` | All orders                    |
| `/admin`  | Add/delete products, dashboard|

---

## API Endpoints

### Products
| Method | Route                | Description              |
|--------|----------------------|--------------------------|
| GET    | `/api/products`      | List all products         |
| GET    | `/api/products/<id>` | Get one product           |
| POST   | `/api/products`      | Add product (admin)       |
| DELETE | `/api/products/<id>` | Delete product (admin)    |

### Payments — Razorpay Flow
| Method | Route                         | Description                      |
|--------|-------------------------------|----------------------------------|
| POST   | `/api/payment/create-order`   | Step 1: Razorpay order banao     |
| POST   | `/api/payment/verify`         | Step 2: Signature verify karo    |
| POST   | `/api/payment/webhook`        | Webhook (server-to-server auto)  |

### Orders & Dashboard
| Method | Route                    | Description          |
|--------|--------------------------|----------------------|
| GET    | `/api/orders`            | All orders           |
| GET    | `/api/dashboard/summary` | Stats summary        |

---

## Razorpay Payment Flow (How it works)

```
1. User "Buy Now" click karta hai
   ↓
2. Frontend → POST /api/payment/create-order (amount, product_id)
   ↓
3. Backend → Razorpay API → order_id milta hai
   ↓
4. Frontend → Razorpay Checkout opens (UPI/Card/Netbanking)
   ↓
5. User payment karta hai → Razorpay sends:
   • razorpay_order_id
   • razorpay_payment_id
   • razorpay_signature
   ↓
6. Frontend → POST /api/payment/verify
   ↓
7. Backend HMAC-SHA256 se signature verify karta hai
   ↓
8. ✅ Verified → Order status "paid" ho jaata hai DB mein
```

---

## Webhook Setup (Recommended)

Razorpay Dashboard → Webhooks → Add Webhook:
- **URL:** `https://your-domain.com/api/payment/webhook`
- **Events:** `payment.captured`
- **Secret:** same value jo `RAZORPAY_WEBHOOK_SECRET` mein diya hai

Webhook automatic payment confirmation karta hai even if user browser close kar de.

---

## Production Deployment

### Gunicorn se (recommended):

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Nginx reverse proxy (`/etc/nginx/sites-available/shop`):

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Database Tables

| Table      | Description                          |
|------------|--------------------------------------|
| `products` | Product catalog                      |
| `orders`   | Razorpay orders (created/paid/failed) |
| `payments` | Verified payment records              |

---

## Test Mode

Razorpay test mode ke liye `rzp_test_*` keys use karo.  
Test card: `4111 1111 1111 1111`, any CVV, any future date.
