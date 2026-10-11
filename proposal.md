# JengaSec APP02 - Mobile Banking API - Cipher Squad

**Team:** Cipher Squad / Mawira
**Repo:** https://github.com/victormawira05-lgtm/mobile-banking-API
**Commit:** 48fd8a0
**Date:** July 2026

## 1. Solution Overview
Secure Mobile Banking API implementing:
- Password Storage: hashlib.scrypt n=2**14, r=8, p=1, dklen=32 + 16-byte salt
- Verification: hmac.compare_digest (constant-time)
- Device Attestation: ECDSA with API_SIGNING_KEY
- Step-Up Auth: TOTP for /payments
- Token Security: Refresh token rotation with reuse detection

## 2. Proof - Tests Passing
pytest -v = 3 passed
- test_health_and_account_flow PASSED
- test_payment_requires_stop_up_and_pass... PASSED
- test_refresh_tokens_rotate_and_reuse_is_detected PASSED

## 3. How to Run
export API_SIGNING_KEY=0123456789abcdef... (64-char hex)
export ALLOW_DEMO_ATTESTATION=1
pytest -v
python -m flask --app app run --host=0.0.0.0 --port=8000

## 4. Team Expertise
Python, Node.js, Bash, Express.js, Java Spring Boot. Azure PaaS (Container Apps, AKS, APIM, ADX/Kusto, App Insights, ADLS Gen2, Key Vault, Entra ID). Observability pipelines with OpenTelemetry. Security: TLS, OAuth2/JWT, RBAC, PII detection, audit logging.

## 5. Screenshots Attached
- 3 passed terminal
- git push 48fd8a0
- app.py line 142-153
