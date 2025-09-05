import os
import json
import uuid
import base64
import httpx
from datetime import datetime, timezone
import zoneinfo
from typing import Literal, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

JKT = zoneinfo.ZoneInfo("Asia/Jakarta")

ESPAY_ENV = os.getenv("ESPAY_ENV", "production")
ESPAY_BASE_URL = (
    "https://api.espay.id" if ESPAY_ENV == "production" else "https://sandbox-api.espay.id"
)
RELATIVE_URL = "/api/v1.0/qr/qr-mpm-generate"
ESPAY_URL = ESPAY_BASE_URL + RELATIVE_URL

ESPAY_PARTNER_ID = os.getenv("ESPAY_PARTNER_ID", "SGWTIEBYMIN")   # X-PARTNER-ID
ESPAY_MERCHANT_ID = os.getenv("ESPAY_MERCHANT_ID", "SGWTIEBYMIN") # body.merchantId
ESPAY_CHANNEL_ID = os.getenv("ESPAY_CHANNEL_ID", "ESPAY")
ESPAY_PRIVATE_KEY_PEM = os.getenv("ESPAY_PRIVATE_KEY_PEM", "").encode()

app = FastAPI(title="Espay QRIS (Direct API QR MPM)", version="1.0")


class Amount(BaseModel):
    value: str = Field(..., pattern=r"^\d+(\.\d{2})$", description="e.g. 150000.00")
    currency: Literal["IDR"] = "IDR"


class QRISRequest(BaseModel):
    partner_reference_no: str = Field(..., min_length=1, max_length=32)
    amount: Amount
    product_code: Literal["QRIS"] = "QRIS"
    validity_period: Optional[str] = Field(None, description="ISO 8601, e.g. 2025-09-05T23:59:00+07:00")


class EspayQRISResponseTemplate(BaseModel):
    response_code: str | None = None
    response_message: str | None = None
    reference_no: str | None = None
    partner_reference_no: str | None = None
    merchant_name: str | None = None
    amount: str | None = None
    qr_url: str | None = None
    qr_content: str | None = None
    qr_image_base64: str | None = None


def now_iso_jkt_seconds() -> str:
    return datetime.now(JKT).replace(microsecond=0).isoformat()


def minify_json(d: dict) -> str:
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False)


def sha256_hex_lower(s: str) -> str:
    from hashlib import sha256
    return sha256(s.encode("utf-8")).hexdigest().lower()


def load_private_key(pem_bytes: bytes):
    if not pem_bytes:
        raise HTTPException(status_code=500, detail="ESPAY_PRIVATE_KEY_PEM tidak di-set")
    try:
        return serialization.load_pem_private_key(pem_bytes, password=None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Private key invalid: {e}")


def sign_rsa_sha256_b64(private_key, message: str) -> str:
    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode()


def make_x_signature(http_method: str, relative_url: str, body: dict, x_timestamp: str) -> str:
    body_min = minify_json(body)
    body_hash = sha256_hex_lower(body_min)
    string_to_sign = f"{http_method}:{relative_url}:{body_hash}:{x_timestamp}"
    pk = load_private_key(ESPAY_PRIVATE_KEY_PEM)
    return sign_rsa_sha256_b64(pk, string_to_sign)


def make_external_id() -> str:
    today = datetime.now(JKT).strftime("%Y%m%d")
    rand = uuid.uuid4().int % (10**16)
    return f"{today}{rand:016d}"[:32]


@app.post("/qris/generate")
async def generate_qris(req: QRISRequest):
    x_timestamp = now_iso_jkt_seconds()

    body = {
        "partnerReferenceNo": req.partner_reference_no,
        "merchantId": ESPAY_MERCHANT_ID,
        "amount": {"value": req.amount.value, "currency": req.amount.currency},
        "additionalInfo": {"productCode": req.product_code},
    }
    if req.validity_period:
        body["validityPeriod"] = req.validity_period

    x_signature = make_x_signature("POST", RELATIVE_URL, body, x_timestamp)

    headers = {
        "Content-Type": "application/json",
        "X-TIMESTAMP": x_timestamp,
        "X-SIGNATURE": x_signature,
        "X-EXTERNAL-ID": make_external_id(),
        "X-PARTNER-ID": ESPAY_PARTNER_ID,
        "CHANNEL-ID": ESPAY_CHANNEL_ID,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0)) as client:
        try:
            r = await client.post(ESPAY_URL, headers=headers, json=body)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Gagal hubungi Espay: {e}")

    content_type = r.headers.get("content-type", "")
    if r.status_code >= 500:
        raise HTTPException(status_code=502, detail=f"Espay error {r.status_code}: {r.text}")
    if "application/json" not in content_type:
        raise HTTPException(status_code=502, detail=f"Unexpected content-type: {content_type}")

    try:
        data = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"Unexpected Espay response: {r.text}")

    return JSONResponse(content=data)


@app.post("/qris/generate/template", response_model=EspayQRISResponseTemplate)
async def generate_qris_template(req: QRISRequest):
    x_timestamp = now_iso_jkt_seconds()

    body = {
        "partnerReferenceNo": req.partner_reference_no,
        "merchantId": ESPAY_MERCHANT_ID,
        "amount": {"value": req.amount.value, "currency": req.amount.currency},
        "additionalInfo": {"productCode": req.product_code},
    }
    if req.validity_period:
        body["validityPeriod"] = req.validity_period

    x_signature = make_x_signature("POST", RELATIVE_URL, body, x_timestamp)

    headers = {
        "Content-Type": "application/json",
        "X-TIMESTAMP": x_timestamp,
        "X-SIGNATURE": x_signature,
        "X-EXTERNAL-ID": make_external_id(),
        "X-PARTNER-ID": ESPAY_PARTNER_ID,
        "CHANNEL-ID": ESPAY_CHANNEL_ID,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0)) as client:
        try:
            r = await client.post(ESPAY_URL, headers=headers, json=body)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Gagal hubungi Espay: {e}")

    if r.status_code >= 500:
        raise HTTPException(status_code=502, detail=f"Espay error {r.status_code}: {r.text}")

    try:
        data = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"Unexpected Espay response: {r.text}")

    tmpl = EspayQRISResponseTemplate(
        response_code=data.get("responseCode"),
        response_message=data.get("responseMessage"),
        reference_no=(data.get("additionalInfo") or {}).get("referenceNo"),
        partner_reference_no=(data.get("additionalInfo") or {}).get("partnerReferenceNo"),
        merchant_name=(data.get("additionalInfo") or {}).get("merchantName"),
        amount=(data.get("additionalInfo") or {}).get("amount"),
        qr_url=data.get("qrUrl"),
        qr_content=data.get("qrContent"),
        qr_image_base64=data.get("qrImage"),
    )
    return tmpl
