# Mobile Banking - PayPal AI

Kenya-focused mobile banking with PayPal + AI Coach.

## Features
- Pay with PayPal Sandbox API (create order + capture)
- AI Financial Insights (spending analysis, savings tips)
- AI Chat Coach

## Run
Backend: `python app.py` (runs on 0.0.0.0:8000)
Frontend: `cd frontend && npm install && npm run dev`

## API
- POST /api/paypal/create-order {amount}
- POST /api/paypal/capture/:id
- POST /api/ai/insights {transactions}
- POST /api/ai/chat {message}

Works in mock mode without API keys for judges. Add PAYPAL_CLIENT_ID, PAYPAL_SECRET, OPENAI_API_KEY to .env for live mode.

## Demo
https://YOUR-CODESPACE-3000.app.github.dev
