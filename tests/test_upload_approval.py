import asyncio

from fintech_uploads.upload_approval import UploadRequest, decide_upload


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, str]] = []

    async def presign_upload(
        self, key: str, *, content_type: str, max_bytes: int, idempotency_key: str
    ) -> str:
        self.calls.append((key, content_type, max_bytes, idempotency_key))
        return "https://uploads.example/signed"


def test_high_risk_evidence_requires_review_without_signing() -> None:
    client = RecordingClient()
    request = UploadRequest(
        payment_id="pay_1042",
        event="payout_review",
        risk_level="high",
        filename="beneficiary.png",
        content_type="image/png",
        size_bytes=800_000,
        actor_id="risk_9",
    )

    decision = asyncio.run(decide_upload(request, client))  # type: ignore[arg-type]

    assert decision.approved is False
    assert decision.notification.action == "manual_review_required"
    assert decision.notification.payment_id == "pay_1042"
    assert client.calls == []


def test_medium_risk_evidence_gets_a_scoped_idempotent_upload() -> None:
    client = RecordingClient()
    request = UploadRequest(
        payment_id="pay_1042",
        event="dispute_opened",
        risk_level="medium",
        filename="receipt.pdf",
        content_type="application/pdf",
        size_bytes=240_000,
        actor_id="ops_7",
    )

    decision = asyncio.run(decide_upload(request, client))  # type: ignore[arg-type]

    assert decision.approved is True
    assert decision.method == "PUT"
    assert decision.notification.action == "upload_authorized"
    assert client.calls == [
        (
            "payments/pay_1042/dispute_opened/receipt.pdf",
            "application/pdf",
            240_000,
            "upload:pay_1042:dispute_opened:receipt.pdf",
        )
    ]
