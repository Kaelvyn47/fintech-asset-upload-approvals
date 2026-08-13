import json
import os
import urllib.request

payload = {
    "payment_id": "pay_1042",
    "event": "dispute_opened",
    "risk_level": "medium",
    "filename": "receipt.pdf",
    "content_type": "application/pdf",
    "size_bytes": 240000,
    "actor_id": "ops_7",
}
request = urllib.request.Request(
    os.environ.get("UPLOAD_SERVICE_URL", "http://127.0.0.1:8000/payment-assets/upload-decision"),
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request) as response:
    print(json.dumps(json.load(response), indent=2))
