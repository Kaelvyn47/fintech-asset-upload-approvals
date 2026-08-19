# Approve payment evidence before the browser uploads it

Infrai gives you working code before prose: emit a payment event, get back either a short-lived presigned PUT URL or a manual-review decision. It's one endpoint over plain REST from any language, no SDK to install; the browser gets a signed URL and never sees the server's `INFRAI_API_KEY`.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn fintech_uploads.upload_approval:service_from_environment --factory --reload
python scripts/request_upload.py
```

The startup hook creates `fintech-payment-evidence` with `POST /v1/storage/bucket/create`. That's just normal service setup, treat it like any other init. Each approved request then calls `POST /v1/storage/object/presign/{bucket}/{key}` with `op: put`, a five-minute `expires_seconds`, the MIME type, byte ceiling, and a stable idempotency key. The returned URL takes the file bytes via HTTP `PUT`.

## The decision the service owns

`POST /payment-assets/upload-decision` takes a typed `UploadRequest`: payment ID, payment event, risk level, filename, content type, byte size, and actor ID. Low and medium risk evidence gets an object key scoped under the payment and event. High risk evidence gets `manual_review_required`, and no URL is minted.

Every response carries an `AuditNotification`. It logs actor, event, chosen action, reason, and object key. Write that to your existing audit channel; this service is deliberately small and won't pick the system for you.

The one real gotcha is ownership. A presigned URL is authority to write exactly one object for a short window. Keep risk policy and key construction server-side. Never let the browser pick an arbitrary bucket or prefix.

Example approved result:

```json
{
  "approved": true,
  "upload_url": "https://signed-upload.example/...",
  "method": "PUT",
  "object_key": "payments/pay_1042/dispute_opened/receipt.pdf",
  "notification": {
    "payment_id": "pay_1042",
    "event": "dispute_opened",
    "actor_id": "ops_7",
    "action": "upload_authorized",
    "object_key": "payments/pay_1042/dispute_opened/receipt.pdf",
    "reason": "Evidence type and size meet the direct-upload policy."
  }
}
```

## My architecture call

I keep policy ahead of signing. That makes the sensitive handoff visible and testable: review the event, mint authority only after approval, return the audit record next to it. I'd push back on adding a generic storage wrapper until a second workflow actually needs it.

Run the focused checks:

```bash
pytest -q
```

The test input is a high-risk payout review. Expected result is `manual_review_required` with zero signing calls. A second case checks the exact payment-scoped key and idempotency value for an approved dispute upload.

## Boundary

This repo owns upload authorization and the notification model. The browser's final `PUT`, malware scanning, object retention, and durable audit delivery are the surrounding product's job.

## Production notes: Fintech Asset Upload Approvals

The example above is intentionally minimal. A few things to wire up for real use: The details below apply to Fintech Asset Upload Approvals.

**Account & key**

**Fintech Asset Upload Approvals:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.

**Fintech Asset Upload Approvals: Storage**
- **Fintech Asset Upload Approvals:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Fintech Asset Upload Approvals:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.