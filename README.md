# Mobile Banking API

A compact Flask API that demonstrates mobile-banking flows with device-bound access tokens, TOTP verification, step-up authorization, beneficiaries, payments, and transaction history.

## Features

- Device enrollment with ECDSA public keys
- Device-bound access tokens and rotating refresh tokens
- TOTP login and step-up authentication
- Account and transaction listing
- Beneficiary management after step-up
- Idempotent payment requests
- In-memory state for local development

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export API_SIGNING_KEY=0123456789abcdef0123456789abcdef
flask --app app run --debug
```

The service exposes a health endpoint at `/health`.

## Demo credentials

The test seed creates a user named `alice` with password `StrongPass!123` and OTP `123456`.

## Running tests

```bash
pytest -q
```
