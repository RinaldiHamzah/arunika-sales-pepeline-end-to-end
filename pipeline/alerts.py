"""Optional failure notification without making alerts a pipeline dependency."""
import json
import os
from urllib.request import Request, urlopen


def notify_pipeline_failure(run_id, error_message):
    webhook = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    if not webhook:
        return False
    payload = json.dumps({"text": f"Arunika pipeline FAILED: run_id={run_id}; error={error_message}"}).encode()
    try:
        request = Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5):
            return True
    except Exception:
        return False
