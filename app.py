import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import struct
import threading
import time
from functools import wraps

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from flask import Flask, g, jsonify, request

API_SIGNING_KEY = os.environ.get("API_SIGNING_KEY")
if not API_SIGNING_KEY:
    raise RuntimeError("API_SIGNING_KEY must be set before starting the API")
if len(bytes.fromhex(API_SIGNING_KEY)) != 32:
    raise RuntimeError("API_SIGNING_KEY must decode to exactly 32 bytes")

SERVER_KEY = bytes.fromhex(API_SIGNING_KEY)
ACCESS_TTL = 300
REFRESH_TTL = 7 * 24 * 3600
PROOF_SKEW = 60
STEPUP_TTL = 300
MAX_PAYMENT_MINOR = 5_000_000
ALLOW_DEMO_ATTESTATION = os.environ.get("ALLOW_DEMO_ATTESTATION") == "1"

log = logging.getLogger("bankapi")
LOCK = threading.RLock()

USERS = {}
USERS_BY_NAME = {}
DEVICES = {}
FAMILIES = {}
REFRESH = {}
SEEN_JTI = {}
ACCOUNTS = {}
BENEFICIARIES = {}
PAYMENTS = {}
IDEM = {}
TXNS = []


class ApiError(Exception):
    def __init__(self, status, code):
        self.status = status
        self.code = code


def b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def b64u_dec(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))


def sha256(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def rate_limit(key: str, limit: int, window: int):
    now = time.time()
    with LOCK:
        bucket = _RATE.setdefault(key, [])
        bucket[:] = [ts for ts in bucket if ts > now - window]
        if len(bucket) >= limit:
            raise ApiError(429, "rate_limited")
        bucket.append(now)


_RATE = {}
AUDIT = []


def audit(event: str, **fields):
    with LOCK:
        previous = AUDIT[-1]["hash"] if AUDIT else "0" * 64
        record = {"ts": int(time.time()), "event": event, **fields, "prev": previous}
        record["hash"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        AUDIT.append(record)


def verify_audit_chain():
    previous = "0" * 64
    for record in AUDIT:
        body = {key: value for key, value in record.items() if key != "hash"}
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        if record["prev"] != previous or record["hash"] != digest:
            return False
        previous = record["hash"]
    return True


def reset_state():
    global USERS, USERS_BY_NAME, DEVICES, FAMILIES, REFRESH, SEEN_JTI, ACCOUNTS, BENEFICIARIES, PAYMENTS, IDEM, TXNS, _RATE, AUDIT
    USERS = {}
    USERS_BY_NAME = {}
    DEVICES = {}
    FAMILIES = {}
    REFRESH = {}
    SEEN_JTI = {}
    ACCOUNTS = {}
    BENEFICIARIES = {}
    PAYMENTS = {}
    IDEM = {}
    TXNS = []
    _RATE = {}
    AUDIT = []


def s(regex=None, minimum=1, maximum=64):
    return str, lambda value: minimum <= len(value) <= maximum and (regex is None or __import__("re").fullmatch(regex, value) is not None)


def n(minimum, maximum):
    return int, lambda value: minimum <= value <= maximum


def body(schema):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_body")
    if set(data) - set(schema):
        raise ApiError(400, "unknown_fields")
    result = {}
    for key, (typ, check) in schema.items():
        value = data.get(key)
        if key not in data or not isinstance(value, typ) or (typ is int and isinstance(value, bool)):
            raise ApiError(400, "invalid_field")
        if not check(value):
            raise ApiError(400, "invalid_field")
        result[key] = value
    return result


def hash_password(password: str) -> bytes:
    salt = secrets.token_bytes(16)
    return salt + hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


def verify_password(password: str, stored: bytes) -> bool:
    if not stored:
        return False
    salt, digest = stored[:16], stored[16:]
    candidate = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(candidate, digest)


def totp(secret: bytes, ts=None, step=30, algorithm=hashlib.sha256) -> str:
    counter = int((ts if ts is not None else time.time()) // step)
    mac = hmac.new(secret, struct.pack(">Q", counter), algorithm).digest()
    offset = mac[-1] & 0xF
    value = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10**6:06d}"


def verify_totp(user: dict, code: str) -> bool:
    now = time.time()
    for drift in (-1, 0, 1):
        match = totp(user["totp_secret"], now + drift * 30)
        if hmac.compare_digest(match, code):
            if int((now + drift * 30) // 30) <= user["last_totp_counter"]:
                return False
            user["last_totp_counter"] = int((now + drift * 30) // 30)
            return True
    return False


def load_pubkey(pem: str):
    try:
        key = serialization.load_pem_public_key(pem.encode())
    except Exception as exc:
        raise ApiError(400, "invalid_public_key") from exc
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        raise ApiError(400, "invalid_public_key")
    return key


def verify_attestation(attestation: str) -> bool:
    return ALLOW_DEMO_ATTESTATION and attestation == "demo-attestation"


def sign_access(claims: dict) -> str:
    payload = b64u(json.dumps(claims, separators=(",", ":")).encode())
    return payload + "." + b64u(hmac.new(SERVER_KEY, payload.encode(), hashlib.sha256).digest())


def verify_access(token: str) -> dict:
    try:
        if len(token) > 1024:
            raise ValueError
        payload, signature = token.split(".")
        expected = b64u(hmac.new(SERVER_KEY, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        claims = json.loads(b64u_dec(payload))
        if claims.get("iss") != "mobile-banking-api" or claims.get("exp") is None:
            raise ValueError
        if claims["exp"] < time.time():
            raise ValueError
        return claims
    except Exception as exc:
        raise ApiError(401, "unauthorized") from exc


def verify_proof(device_id: str, key, auth_token_hash: str):
    raw = request.headers.get("X-Device-Proof", "")
    try:
        if not raw or len(raw) > 2048:
            raise ValueError
        envelope = json.loads(b64u_dec(raw))
        if not isinstance(envelope.get("method"), str) or not isinstance(envelope.get("path"), str):
            raise ValueError
        if not isinstance(envelope.get("ts"), int) or not isinstance(envelope.get("jti"), str):
            raise ValueError
        if abs(time.time() - envelope["ts"]) > PROOF_SKEW:
            raise ValueError
        message = "|".join([
            envelope["method"],
            envelope["path"],
            str(envelope["ts"]),
            envelope["jti"],
            auth_token_hash,
        ]).encode()
        signature = envelope.get("sig")
        if not isinstance(signature, str):
            raise ValueError
        key.verify(b64u_dec(signature), message, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise ApiError(401, "invalid_proof")
    now = time.time()
    with LOCK:
        for seen_jti, expiration in list(SEEN_JTI.items()):
            if expiration < now:
                del SEEN_JTI[seen_jti]
        pair = f"{device_id}:{envelope['jti']}"
        if pair in SEEN_JTI:
            raise ApiError(401, "invalid_proof")
        SEEN_JTI[pair] = now + 2 * PROOF_SKEW


def issue_tokens(user_id: str, device_id: str, family: str = None) -> dict:
    now = int(time.time())
    with LOCK:
        if family is None:
            family = secrets.token_hex(16)
            FAMILIES[family] = {"user": user_id, "device": device_id, "revoked": False, "stepup_until": 0}
        refresh = secrets.token_urlsafe(32)
        REFRESH[b64u(sha256(refresh.encode()))] = {"family": family, "used": False, "exp": now + REFRESH_TTL}
    access = sign_access({"iss": "mobile-banking-api", "sub": user_id, "dev": device_id, "fam": family, "jti": secrets.token_hex(8), "iat": now, "exp": now + ACCESS_TTL})
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "DeviceBound",
        "expires_in": ACCESS_TTL,
        "access_expires_at": now + ACCESS_TTL,
        "refresh_expires_at": now + REFRESH_TTL,
    }


def revoke_family(family: str):
    with LOCK:
        if family in FAMILIES:
            FAMILIES[family]["revoked"] = True


def require_auth(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("DeviceBound "):
            raise ApiError(401, "unauthorized")
        claims = verify_access(auth[len("DeviceBound "):])
        family = FAMILIES.get(claims["fam"])
        device = DEVICES.get(claims["dev"])
        if not family or family["revoked"] or not device or device["revoked"]:
            raise ApiError(401, "unauthorized")
        verify_proof(device["id"], device["auth_key"], b64u(sha256(auth[len("DeviceBound "):].encode())))
        g.user_id = claims["sub"]
        g.device = device
        g.family = claims["fam"]
        rate_limit(f"user:{g.user_id}", 120, 60)
        return func(*args, **kwargs)

    return wrapper


def owned(store: dict, object_id: str):
    obj = store.get(object_id)
    owner = obj and (obj.get("owner") or obj.get("user"))
    if not obj or owner != g.user_id:
        raise ApiError(404, "not_found")
    return obj


def require_idempotency_key(scope: str, payload: dict = None, user_id: str = None):
    key = request.headers.get("Idempotency-Key", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", key):
        raise ApiError(400, "invalid_idempotency_key")
    user = user_id or getattr(g, "user_id", None)
    material = {"scope": scope, "user": user, "payload": payload or {}}
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    prior = IDEM.get((user, key, scope)) if user else None
    if prior:
        if prior["hash"] != digest:
            raise ApiError(422, "idempotency_key_reuse")
        return prior["response"], True
    return {"hash": digest}, False


def check_credentials(username: str, password: str, otp: str):
    with LOCK:
        user = USERS_BY_NAME.get(username)
        if not user:
            return None
        if user["locked_until"] > time.time():
            return None
        if verify_password(password, user["pw"]) and verify_totp(user, otp):
            user["fails"] = 0
            return user
        user["fails"] = user.get("fails", 0) + 1
        if user["fails"] >= 5:
            user["locked_until"] = time.time() + min(900, 30 * 2 ** (user["fails"] - 5))
        return None


def create_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.before_request
    def enforce_json_content_type():
        if request.method in {"POST", "PUT", "PATCH"} and request.content_length and request.mimetype != "application/json":
            raise ApiError(415, "unsupported_media_type")

    @app.after_request
    def harden(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Type"] = "application/json" if response.mimetype == "application/json" else response.headers.get("Content-Type", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        return response

    @app.errorhandler(ApiError)
    def on_api_error(error):
        return jsonify({"error": error.code}), error.status

    @app.errorhandler(404)
    def on_404(_):
        return jsonify({"error": "not_found"}), 404

    @app.errorhandler(405)
    def on_405(_):
        return jsonify({"error": "method_not_allowed"}), 405

    @app.errorhandler(413)
    def on_413(_):
        return jsonify({"error": "payload_too_large"}), 413

    @app.errorhandler(415)
    def on_415(_):
        return jsonify({"error": "unsupported_media_type"}), 415

    @app.errorhandler(Exception)
    def on_error(error):
        log.exception("unhandled")
        return jsonify({"error": "internal_error"}), 500

    @app.post("/v1/devices")
    def enroll_device():
        rate_limit(f"ip:{request.remote_addr}:auth", 20, 60)
        request_payload = body({
            "username": s(r"[a-z0-9_.-]+", 3, 32),
            "password": s(None, 1, 128),
            "otp": s(r"\d{6}", 6, 6),
            "auth_public_key": s(None, 50, 400),
            "tx_public_key": s(None, 50, 400),
            "attestation": s(None, 1, 4096),
        })
        auth_key = load_pubkey(request_payload["auth_public_key"])
        tx_key = load_pubkey(request_payload["tx_public_key"])
        user = check_credentials(request_payload["username"], request_payload["password"], request_payload["otp"])
        if not user or not verify_attestation(request_payload["attestation"]):
            raise ApiError(401, "invalid_credentials")
        idem = require_idempotency_key("device-enroll", request_payload, user["id"])
        if idem[1]:
            return jsonify(idem[0]), 200
        device_id = "dev_" + secrets.token_hex(8)
        response = {"device_id": device_id}
        with LOCK:
            DEVICES[device_id] = {"id": device_id, "user": user["id"], "auth_key": auth_key, "tx_key": tx_key, "revoked": False}
            IDEM[(user["id"], request.headers["Idempotency-Key"], "device-enroll")] = {"hash": idem[0]["hash"], "response": response}
        return jsonify(response), 201

    @app.delete("/v1/devices/<dev_id>")
    @require_auth
    def revoke_device(dev_id):
        device = owned(DEVICES, dev_id)
        idem = require_idempotency_key(f"device-revoke:{dev_id}", {"device_id": dev_id})
        if idem[1]:
            return "", 200
        with LOCK:
            device["revoked"] = True
            for family in FAMILIES.values():
                if family["device"] == dev_id:
                    family["revoked"] = True
            IDEM[(g.user_id, request.headers["Idempotency-Key"], f"device-revoke:{dev_id}")] = {"hash": idem[0]["hash"], "response": {}}
        return "", 204

    @app.post("/v1/auth/token")
    def login():
        rate_limit(f"ip:{request.remote_addr}:auth", 20, 60)
        payload = body({
            "username": s(r"[a-z0-9_.-]+", 3, 32),
            "password": s(None, 1, 128),
            "otp": s(r"\d{6}", 6, 6),
            "device_id": s(r"dev_[0-9a-f]{16}", 20, 20),
            "device_proof": s(None, 0, 1024),
        })
        device = DEVICES.get(payload["device_id"])
        if not device or device["revoked"]:
            raise ApiError(401, "invalid_credentials")
        user = check_credentials(payload["username"], payload["password"], payload["otp"])
        if not user or user["id"] != device["user"]:
            raise ApiError(401, "invalid_credentials")
        if payload["device_proof"]:
            verify_proof(device["id"], device["auth_key"], "")
        return jsonify(issue_tokens(user["id"], device["id"]))

    @app.post("/v1/auth/refresh")
    def refresh():
        rate_limit(f"ip:{request.remote_addr}:auth", 20, 60)
        payload = body({"refresh_token": s(r"[A-Za-z0-9_-]+", 20, 100)})
        idem = require_idempotency_key("refresh", payload)
        if idem[1]:
            return jsonify(idem[0]), 200
        record = REFRESH.get(b64u(sha256(payload["refresh_token"].encode())))
        if not record:
            raise ApiError(401, "invalid_token")
        family = FAMILIES.get(record["family"])
        device = family and DEVICES.get(family["device"])
        if not device or device["revoked"]:
            raise ApiError(401, "invalid_token")
        with LOCK:
            if record["used"]:
                revoke_family(record["family"])
                raise ApiError(401, "invalid_token")
            if family["revoked"] or record["exp"] < time.time():
                raise ApiError(401, "invalid_token")
            record["used"] = True
            token = issue_tokens(family["user"], device["id"], family=record["family"])
            IDEM[(family["user"], request.headers["Idempotency-Key"], "refresh")] = {"hash": idem[0]["hash"], "response": token}
        return jsonify(token)

    @app.post("/v1/auth/logout")
    @require_auth
    def logout():
        idem = require_idempotency_key(f"logout:{g.family}", {"family": g.family})
        if idem[1]:
            return "", 200
        revoke_family(g.family)
        with LOCK:
            IDEM[(g.user_id, request.headers["Idempotency-Key"], f"logout:{g.family}")] = {"hash": idem[0]["hash"], "response": {}}
        return "", 204

    @app.post("/v1/auth/step-up")
    @require_auth
    def step_up():
        payload = body({"otp": s(r"\d{6}", 6, 6)})
        idem = require_idempotency_key(f"step-up:{g.family}", payload)
        if idem[1]:
            return jsonify(idem[0]), 200
        with LOCK:
            if not verify_totp(USERS[g.user_id], payload["otp"]):
                raise ApiError(401, "invalid_credentials")
            FAMILIES[g.family]["stepup_until"] = time.time() + STEPUP_TTL
            IDEM[(g.user_id, request.headers["Idempotency-Key"], f"step-up:{g.family}")] = {"hash": idem[0]["hash"], "response": {"step_up_valid_for": STEPUP_TTL}}
        return jsonify({"step_up_valid_for": STEPUP_TTL})

    @app.get("/v1/accounts")
    @require_auth
    def list_accounts():
        return jsonify([
            {"id": account["id"], "currency": account["currency"], "balance_minor": account["balance_minor"], "number": "**" + account["number"][-4:]}
            for account in ACCOUNTS.values() if account["owner"] == g.user_id
        ])

    @app.get("/v1/accounts/<acc_id>/transactions")
    @require_auth
    def list_transactions(acc_id):
        owned(ACCOUNTS, acc_id)
        if set(request.args) - {"limit", "before_seq"}:
            raise ApiError(400, "unknown_params")
        limit = request.args.get("limit", "20")
        before = request.args.get("before_seq", "")
        if not limit.isdigit() or not 1 <= int(limit) <= 50 or (before and not before.isdigit()):
            raise ApiError(400, "invalid_params")
        rows = [transaction for transaction in reversed(TXNS) if transaction["account_id"] == acc_id and (not before or transaction["seq"] < int(before))]
        return jsonify(rows[:int(limit)])

    @app.post("/v1/beneficiaries")
    @require_auth
    def add_beneficiary():
        if time.time() > FAMILIES[g.family]["stepup_until"]:
            raise ApiError(403, "step_up_required")
        payload = body({"name": s(r"[A-Za-z0-9 .'-]+", 1, 60), "account_number": s(r"\d{8,16}", 8, 16), "bank_code": s(r"[A-Z0-9]{4,11}", 4, 11)})
        idem = require_idempotency_key(f"beneficiary:{g.user_id}", payload)
        if idem[1]:
            return jsonify(idem[0]), 200
        beneficiary_id = "ben_" + secrets.token_hex(8)
        response = {"id": beneficiary_id, **payload}
        with LOCK:
            BENEFICIARIES[beneficiary_id] = {"id": beneficiary_id, "owner": g.user_id, **payload}
            IDEM[(g.user_id, request.headers["Idempotency-Key"], f"beneficiary:{g.user_id}")] = {"hash": idem[0]["hash"], "response": response}
        return jsonify(response), 201

    @app.get("/v1/beneficiaries")
    @require_auth
    def list_beneficiaries():
        return jsonify([beneficiary for beneficiary in BENEFICIARIES.values() if beneficiary["owner"] == g.user_id])

    @app.post("/v1/payments")
    @require_auth
    def create_payment():
        payload = body({
            "from_account_id": s(r"acc_[0-9a-f]{16}", 20, 20),
            "beneficiary_id": s(r"ben_[0-9a-f]{16}", 20, 20),
            "amount_minor": n(1, MAX_PAYMENT_MINOR),
            "currency": s(r"[A-Z]{3}", 3, 3),
            "reference": s(r"[A-Za-z0-9 .,_-]*", 0, 35),
        })
        idem = require_idempotency_key(f"payment:{g.user_id}", payload)
        if idem[1]:
            return jsonify(idem[0]), 200
        from_account = owned(ACCOUNTS, payload["from_account_id"])
        beneficiary = owned(BENEFICIARIES, payload["beneficiary_id"])
        with LOCK:
            if from_account["balance_minor"] < payload["amount_minor"]:
                raise ApiError(422, "insufficient_funds")
            payment_id = "pay_" + secrets.token_hex(8)
            payment = {
                "id": payment_id,
                **payload,
                "status": "pending",
                "beneficiary_name": beneficiary["name"],
                "created_at": int(time.time()),
            }
            PAYMENTS[payment_id] = payment
            canonical = json.dumps({"payment_id": payment_id, **payload}, separators=(",", ":"), sort_keys=True)
            response = {"payment_id": payment_id, "signed_payload": b64u(hashlib.sha256(canonical.encode()).digest())}
            IDEM[(g.user_id, request.headers["Idempotency-Key"], f"payment:{g.user_id}")] = {"hash": idem[0]["hash"], "response": response}
            return jsonify(response), 201

    return app


def seed_demo_user(username: str = "alice", password: str = "StrongPass!123"):
    reset_state()
    secret = base64.b32encode(b"1234567890123456")
    user = {
        "id": "user_001",
        "username": username,
        "pw": hash_password(password),
        "totp_secret": secret,
        "last_totp_counter": 0,
        "fails": 0,
        "locked_until": 0,
    }
    USERS[user["id"]] = user
    USERS_BY_NAME[username] = user
    account_id = "acc_" + secrets.token_hex(8)
    ACCOUNTS[account_id] = {"id": account_id, "owner": user["id"], "currency": "USD", "balance_minor": 500000, "number": "1000000001"}
    with LOCK:
        TXNS.append({"seq": 1, "account_id": account_id, "amount_minor": 500000, "type": "credit", "description": "Opening balance", "ts": int(time.time())})
    return user


app = create_app()
