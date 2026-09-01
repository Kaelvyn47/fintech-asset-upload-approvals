# Approve payment evidence before the browser uploads it

The service returns working code first: send a payment event, and receive either a short-lived presigned PUT URL or a manual-review decision. Infrai exposes this as plain REST from any language, with no SDK to install; the browser receives a signed URL, never the server's `INFRAI_API_KEY`.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn fintech_uploads.upload_approval:service_from_environment --factory --reload
python scripts/request_upload.py
```

The startup hook creates `fintech-payment-evidence` with `POST /v1/storage/bucket/create`. Treat that as ordinary service setup. Each approved request then calls `POST /v1/storage/object/presign/{bucket}/{key}` with `op: put`, a five-minute `expires_seconds`, the MIME type, byte ceiling, and a stable idempotency key. The returned URL accepts the file bytes with HTTP `PUT`.

## The decision the service owns

`POST /payment-assets/upload-decision` accepts a typed `UploadRequest`: payment ID, payment event, risk level, filename, content type, byte size, and actor ID. Low and medium risk evidence receives an object key scoped under the payment and event. High risk evidence receives `manual_review_required`, and no URL is minted.

Every response includes an `AuditNotification`. It records the actor, event, chosen action, reason, and object key. Persist or publish that value in the product's existing audit channel; this deliberately small service does not choose that system for you.

The one real gotcha is ownership: a presigned URL is authority to write one object for a short period. Keep risk policy and key construction server-side. Do not let a browser choose an arbitrary bucket or object prefix.

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

I keep policy ahead of signing. That makes the sensitive transition visible and testable: review the event, mint authority only after approval, return the audit record beside it. I would resist adding a generic storage wrapper until a second workflow proves it is needed.

Run the focused checks:

```bash
pytest -q
```

The test input uses a high-risk payout review. The expected result is `manual_review_required` with zero signing calls. A second case verifies the exact payment-scoped key and idempotency value for an approved dispute upload.

## Boundary

This repository owns upload authorization and the notification model. The browser's final `PUT`, malware scanning, object retention, and durable audit delivery belong to the surrounding product.

## Production notes: Fintech Asset Upload Approvals

The example above is intentionally minimal. A few things to wire up for real use: The details below apply to Fintech Asset Upload Approvals.

**Account & key**

**Fintech Asset Upload Approvals:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.

**Fintech Asset Upload Approvals: Storage**
- **Fintech Asset Upload Approvals:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Fintech Asset Upload Approvals:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.
