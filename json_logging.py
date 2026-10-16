import json
import time
from flask import request

def init_json_logging(app):
    @app.after_request
    def log_json(response):
        try:
            print(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "src_ip": request.headers.get('X-Forwarded-For', request.remote_addr) or "-",
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "user": "-",
                "action": request.path.strip('/').replace('/', '.') or "root"
            }), flush=True)
        except:
            pass
        return response