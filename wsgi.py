import os
os.environ.setdefault("API_SIGNING_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
os.environ.setdefault("ALLOW_DEMO_ATTESTATION", "1")
from app import create_app
application = create_app()
app = application
print(f"SUCCESS: Loaded Flask app via create_app() -> {application}", flush=True)
