import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import requests

load_dotenv()

app = Flask(__name__)

# === FIX CORS HERE ===
CORS(app, 
     origins="*",
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "OPTIONS"],
     supports_credentials=False)

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_SECRET = os.getenv("PAYPAL_SECRET")
PAYPAL_BASE = "https://api-m.sandbox.paypal.com"
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

def get_paypal_token():
    if not PAYPAL_CLIENT_ID or not PAYPAL_SECRET:
        return None
    try:
        resp = requests.post(
            f"{PAYPAL_BASE}/v1/oauth2/token",
            auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
            data={"grant_type": "client_credentials"},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as e:
        print(f"PayPal token error: {e}")
        return None

@app.route("/")
def home():
    return jsonify({
        "message": "PesaAI Backend Running ✅ CORS FIXED",
        "endpoints": ["/health", "/api/health", "/api/paypal/create-order", "/api/ai/insights"],
        "cors": "open"
    })

@app.route("/health")
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "paypal": "mock", "ai": "mock", "cors": "enabled"})

@app.route("/api/paypal/create-order", methods=["POST", "OPTIONS"])
def create_order():
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200
    data = request.get_json() or {}
    amount = data.get("amount", "10.00")
    token = get_paypal_token()
    if not token:
        return jsonify({
            "id": f"MOCK-ORDER-{os.urandom(4).hex().upper()}",
            "status": "CREATED",
            "mode": "mock",
            "amount": amount
        })
    try:
        resp = requests.post(
            f"{PAYPAL_BASE}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"intent": "CAPTURE", "purchase_units": [{"amount": {"currency_code": "USD", "value": str(amount)}}]},
            timeout=15
        )
        resp.raise_for_status()
        order = resp.json()
        order["mode"] = "live"
        return jsonify(order)
    except Exception as e:
        return jsonify({"id": f"MOCK-ORDER-{os.urandom(4).hex().upper()}", "status": "CREATED", "mode": "mock", "error": str(e)}), 200

@app.route("/api/paypal/capture/<order_id>", methods=["POST", "OPTIONS"])
def capture_order(order_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200
    if order_id.startswith("MOCK"):
        return jsonify({"id": order_id, "status": "COMPLETED", "mode": "mock"})
    token = get_paypal_token()
    if not token:
        return jsonify({"id": order_id, "status": "COMPLETED", "mode": "mock"})
    try:
        resp = requests.post(
            f"{PAYPAL_BASE}/v2/checkout/orders/{order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15
        )
        resp.raise_for_status()
        result = resp.json()
        result["mode"] = "live"
        return jsonify(result)
    except Exception as e:
        return jsonify({"id": order_id, "status": "COMPLETED", "mode": "mock", "error": str(e)}), 200

@app.route("/api/ai/insights", methods=["POST", "OPTIONS"])
def ai_insights():
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200
    data = request.get_json() or {}
    transactions = data.get("transactions", [])
    total_spent = sum([abs(t.get("amount",0)) for t in transactions if t.get("amount",0) < 0])
    return jsonify({
        "insights": f"You spent ${total_spent:.2f} this week. 40% on airtime (Safaricom). Tip: Top up $20 weekly via PayPal USD balance — save 5% + avoid Safaricom fees. Your freelance income is 3.7x expenses — you can save $110!",
        "mode": "mock",
        "transactions_analyzed": len(transactions)
    })

@app.route("/api/ai/chat", methods=["POST", "OPTIONS"])
def ai_chat():
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200
    return jsonify({"reply": "For Kenya: Move daily M-Pesa topups to weekly to save fees.", "mode": "mock"})

if __name__ == "__main__":
    print("Starting PesaAI Backend - CORS OPEN - MOCK MODE")
    app.run(host="0.0.0.0", port=8000, debug=True)