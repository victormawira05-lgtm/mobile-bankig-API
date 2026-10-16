from app import create_app
from json_logging import init_json_logging
application = create_app()
init_json_logging(application)
app = application
print(f"SUCCESS: Loaded Flask app via create_app() -> {application}", flush=True)