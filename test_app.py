import base64
import hashlib
import hmac
import importlib
import json
import os
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


os.environ.setdefault("API_SIGNING_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
os.environ.setdefault("ALLOW_DEMO_ATTESTATION", "1")


@pytest.fixture
def client():
    app_module = importlib.import_module("app")
    app_module.reset_state()
    app = app_module.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _pem_key():
    key = ec.generate_private_key(ec.SECP256R1())
    return key, key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def _sign(message: str, key) -> str:
    sig = key.sign(message.encode(), ec.ECDSA(hashes.SHA256()))
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode()


def _proof_headers(method, path, token_value, auth_key, jti="req"):
    app_module = importlib.import_module("app")
    timestamp = int(app_module.time.time())
    token_hash = base64.urlsafe_b64encode(hashlib.sha256(token_value.encode()).digest()).rstrip(b"=").decode()
    message = "|".join([method, path, str(timestamp), jti, token_hash])
    proof = {"method": method, "path": path, "ts": timestamp, "jti": jti, "sig": _sign(message, auth_key)}
    return {
        "Authorization": f"DeviceBound {token_value}",
        "X-Device-Proof": base64.urlsafe_b64encode(json.dumps(proof, separators=(",", ":")).encode()).rstrip(b"=").decode(),
    }


def _otp(app_module, username, timestamp):
    return app_module.totp(app_module.USERS_BY_NAME[username]["totp_secret"], timestamp)


def _device_headers(client, username="alice", password="StrongPass!123", timestamp=1700000000):
    app_module = importlib.import_module("app")
    app_module.seed_demo_user(username=username, password=password)
    auth_key, auth_public_key = _pem_key()
    tx_key, tx_public_key = _pem_key()
    otp = _otp(app_module, username, timestamp)
    response = client.post(
        "/v1/devices",
        headers={"Idempotency-Key": "abcdefghijklmnop"},
        json={
            "username": username,
            "password": password,
            "otp": otp,
            "auth_public_key": auth_public_key,
            "tx_public_key": tx_public_key,
            "attestation": "demo-attestation",
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    device_id = response.get_json()["device_id"]
    return device_id, auth_key, tx_key


def test_health_and_account_flow(client, monkeypatch):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]

    username = "alice"
    app_module = importlib.import_module("app")
    clock = 1700000000
    monkeypatch.setattr(app_module.time, "time", lambda: clock)
    device_id, auth_key, _ = _device_headers(client, username, password="StrongPass!123", timestamp=clock)
    clock += 60
    token = client.post(
        "/v1/auth/token",
        json={
            "username": username,
            "password": "StrongPass!123",
            "otp": _otp(app_module, username, clock),
            "device_id": device_id,
            "device_proof": "",
        },
    )
    assert token.status_code == 200, token.get_data(as_text=True)
    data = token.get_json()
    assert set(data) == {"access_token", "refresh_token", "token_type", "expires_in", "access_expires_at", "refresh_expires_at"}
    assert data["access_token"].split(".")[0].startswith("eyJpc3MiOiJtb2JpbGUtYmFua2luZy1hcGki")
    assert 0 < data["expires_in"] <= 300
    assert data["access_expires_at"] < data["refresh_expires_at"]

    headers = _proof_headers("GET", "/v1/accounts", data["access_token"], auth_key, "probe")
    accounts = client.get("/v1/accounts", headers=headers)
    assert accounts.status_code == 200
    assert len(accounts.get_json()) >= 1

    account = accounts.get_json()[0]
    transactions = client.get(
        f"/v1/accounts/{account['id']}/transactions",
        headers=_proof_headers("GET", f"/v1/accounts/{account['id']}/transactions", data["access_token"], auth_key, "txns"),
    )
    assert transactions.status_code == 200
    assert isinstance(transactions.get_json(), list)

    replay = client.get("/v1/accounts", headers=headers)
    assert replay.status_code == 401
    assert replay.get_json()["error"] == "invalid_proof"


def test_payment_requires_step_up_and_uses_idempotency_key(client, monkeypatch):
    app_module = importlib.import_module("app")
    clock = 1700000000
    monkeypatch.setattr(app_module.time, "time", lambda: clock)
    device_id, auth_key, _ = _device_headers(client, "bob", "CorrectPass!456", timestamp=clock)
    clock += 60
    token = client.post(
        "/v1/auth/token",
        json={
            "username": "bob",
            "password": "CorrectPass!456",
            "otp": _otp(app_module, "bob", clock),
            "device_id": device_id,
            "device_proof": "",
        },
    ).get_json()

    def auth_headers(method, path, token_value, jti="req"):
        return _proof_headers(method, path, token_value, auth_key, jti)

    beneficiary = client.post(
        "/v1/beneficiaries",
        headers=auth_headers("POST", "/v1/beneficiaries", token["access_token"], "beneficiary-before-stepup"),
        json={
            "name": "Jane Doe",
            "account_number": "12345678",
            "bank_code": "BANK01",
        },
    )
    assert beneficiary.status_code == 403
    assert beneficiary.get_json()["error"] == "step_up_required"

    clock += 60
    step_up = client.post(
        "/v1/auth/step-up",
        headers={**auth_headers("POST", "/v1/auth/step-up", token["access_token"], "stepup-bob"), "Idempotency-Key": "stepupbobabcdefghijkl"},
        json={"otp": _otp(app_module, "bob", clock)},
    )
    assert step_up.status_code == 200

    beneficiary = client.post(
        "/v1/beneficiaries",
        headers={**auth_headers("POST", "/v1/beneficiaries", token["access_token"], "beneficiary-after-stepup"), "Idempotency-Key": "beneficiarybob123456"},
        json={
            "name": "Jane Doe",
            "account_number": "12345678",
            "bank_code": "BANK01",
        },
    )
    assert beneficiary.status_code == 201
    beneficiary_id = beneficiary.get_json()["id"]

    accounts = client.get("/v1/accounts", headers=auth_headers("GET", "/v1/accounts", token["access_token"]))
    account = accounts.get_json()[0]
    payment = client.post(
        "/v1/payments",
        headers={**auth_headers("POST", "/v1/payments", token["access_token"], "payment-bob"), "Idempotency-Key": "abcdefghijklmnop"},
        json={
            "from_account_id": account["id"],
            "beneficiary_id": beneficiary_id,
            "amount_minor": 1000,
            "currency": "USD",
            "reference": "rent",
        },
    )
    assert payment.status_code == 201
    payload = payment.get_json()
    assert "signed_payload" in payload

    duplicate = client.post(
        "/v1/payments",
        headers={**auth_headers("POST", "/v1/payments", token["access_token"], "payment-bob-duplicate"), "Idempotency-Key": "abcdefghijklmnop"},
        json={
            "from_account_id": account["id"],
            "beneficiary_id": beneficiary_id,
            "amount_minor": 1000,
            "currency": "USD",
            "reference": "rent",
        },
    )
    assert duplicate.status_code == 200


def test_refresh_tokens_rotate_and_reuse_is_detected(client, monkeypatch):
    app_module = importlib.import_module("app")
    clock = 1700000000
    monkeypatch.setattr(app_module.time, "time", lambda: clock)
    device_id, auth_key, _ = _device_headers(client, "charlie", "SecurePass!789", timestamp=clock)
    clock += 60
    login = client.post(
        "/v1/auth/token",
        json={
            "username": "charlie",
            "password": "SecurePass!789",
            "otp": _otp(app_module, "charlie", clock),
            "device_id": device_id,
            "device_proof": "",
        },
    )
    tokens = login.get_json()
    headers = _proof_headers("POST", "/v1/auth/refresh", tokens["refresh_token"], auth_key)
    refresh = client.post(
        "/v1/auth/refresh",
        headers={**headers, "Idempotency-Key": "refreshcharlie123456"},
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh.status_code == 200
    rotated = refresh.get_json()
    assert rotated["refresh_token"] != tokens["refresh_token"]

    replay = client.post(
        "/v1/auth/refresh",
        headers={**headers, "Idempotency-Key": "refreshcharlie123456"},
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert replay.status_code == 401
    assert replay.get_json()["error"] == "invalid_token"

    current = client.get(
        "/v1/accounts",
        headers=_proof_headers("GET", "/v1/accounts", rotated["access_token"], auth_key, "accounts-after-refresh"),
    )
    assert current.status_code == 401
    assert current.get_json()["error"] == "unauthorized"
