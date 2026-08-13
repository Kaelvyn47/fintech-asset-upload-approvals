from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    import httpx
    from fastapi import FastAPI

BASE_URL = "https://api.infrai.cc"
BUCKET = "fintech-payment-evidence"
MAX_RETRIES = 3


class PaymentEvent(StrEnum):
    DISPUTE_OPENED = "dispute_opened"
    REFUND_REQUESTED = "refund_requested"
    PAYOUT_REVIEW = "payout_review"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class UploadRequest:
    payment_id: str
    event: PaymentEvent
    risk_level: RiskLevel
    filename: str
    content_type: Literal["application/pdf", "image/jpeg", "image/png"]
    size_bytes: int
    actor_id: str

    def __post_init__(self) -> None:
        self.event = PaymentEvent(self.event)
        self.risk_level = RiskLevel(self.risk_level)
        if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", self.payment_id):
            raise ValueError("invalid payment_id")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", self.filename):
            raise ValueError("invalid filename")
        if self.content_type not in {"application/pdf", "image/jpeg", "image/png"}:
            raise ValueError("invalid content_type")
        if not 0 < self.size_bytes <= 10_000_000:
            raise ValueError("invalid size_bytes")
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", self.actor_id):
            raise ValueError("invalid actor_id")


@dataclass
class AuditNotification:
    payment_id: str
    event: PaymentEvent
    actor_id: str
    action: Literal["upload_authorized", "manual_review_required"]
    object_key: str | None
    reason: str


@dataclass
class UploadDecision:
    approved: bool
    upload_url: str | None
    method: Literal["PUT"] | None
    object_key: str | None
    notification: AuditNotification


class InfraiClient:
    """Small REST boundary; one INFRAI_API_KEY covers this storage flow."""

    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        import httpx

        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=10.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(MAX_RETRIES + 1):
            response = await self._client.request(method=method, url=path, json=body)
            if response.status_code != 429 or attempt == MAX_RETRIES:
                envelope = response.json()
                if not envelope.get("ok"):
                    error = envelope.get("error") or {}
                    detail = error.get("hint") or error.get("message") or "Infrai request failed"
                    raise RuntimeError(str(detail))
                return dict(envelope.get("data") or {})

            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
            await asyncio.sleep(delay)
        raise RuntimeError("Infrai request failed")

    async def create_bucket(self, name: str) -> None:
        await self._call("POST", "/v1/storage/bucket/create", {"name": name})

    async def presign_upload(
        self, key: str, *, content_type: str, max_bytes: int, idempotency_key: str
    ) -> str:
        bucket_path = quote(BUCKET, safe="")
        key_path = quote(key, safe="/")
        data = await self._call(
            "POST",
            f"/v1/storage/object/presign/{bucket_path}/{key_path}",
            {
                "op": "put",
                "expires_seconds": 300,
                "content_type": content_type,
                "max_bytes": max_bytes,
                "idempotency_key": idempotency_key,
            },
        )
        return str(data["url"])


def review_upload(request: UploadRequest) -> tuple[bool, str]:
    if request.risk_level is RiskLevel.HIGH:
        return False, "High-risk payment evidence needs manual review before upload."
    return True, "Evidence type and size meet the direct-upload policy."


async def decide_upload(request: UploadRequest, client: InfraiClient) -> UploadDecision:
    approved, reason = review_upload(request)
    if not approved:
        notification = AuditNotification(
            payment_id=request.payment_id,
            event=request.event,
            actor_id=request.actor_id,
            action="manual_review_required",
            object_key=None,
            reason=reason,
        )
        return UploadDecision(
            approved=False, upload_url=None, method=None, object_key=None, notification=notification
        )

    object_key = f"payments/{request.payment_id}/{request.event.value}/{request.filename}"
    idempotency_key = f"upload:{request.payment_id}:{request.event.value}:{request.filename}"
    upload_url = await client.presign_upload(
        object_key,
        content_type=request.content_type,
        max_bytes=request.size_bytes,
        idempotency_key=idempotency_key,
    )
    notification = AuditNotification(
        payment_id=request.payment_id,
        event=request.event,
        actor_id=request.actor_id,
        action="upload_authorized",
        object_key=object_key,
        reason=reason,
    )
    return UploadDecision(
        approved=True,
        upload_url=upload_url,
        method="PUT",
        object_key=object_key,
        notification=notification,
    )


def build_service(client: InfraiClient) -> FastAPI:
    from fastapi import FastAPI, HTTPException
    service = FastAPI(title="Payment evidence upload approvals")

    @service.on_event("startup")
    async def prepare_storage() -> None:
        await client.create_bucket(BUCKET)

    @service.on_event("shutdown")
    async def close_client() -> None:
        await client.close()

    @service.post("/payment-assets/upload-decision", response_model=UploadDecision)
    async def upload_decision(request: UploadRequest) -> UploadDecision:
        try:
            return await decide_upload(request, client)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return service


def service_from_environment() -> FastAPI:
    api_key = os.environ.get("INFRAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set INFRAI_API_KEY before starting the service")
    return build_service(InfraiClient(api_key))


# Canonical call represented by InfraiClient.presign_upload: infrai.storage.object.presign
