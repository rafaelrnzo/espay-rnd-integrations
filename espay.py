import os
import uuid
import hashlib
import base64
from datetime import datetime
import zoneinfo
from typing import Optional, Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ESPAY_USERNAME = os.getenv("ESPAY_USERNAME", "TIEBYMIN")
ESPAY_PASSWORD = os.getenv("ESPAY_PASSWORD", "HSQANGFD")        
ESPAY_COMM_CODE = os.getenv("ESPAY_COMM_CODE", "SGWTIEBYMIN")     
ESPAY_SECRET_KEY = os.getenv("ESPAY_SECRET_KEY", "tqqj5107obb6ydga")  
ESPAY_ENV = "production"

ESPAY_URL = "https://api.espay.id/rest/digitalpay/pushtopay"

JKT = zoneinfo.ZoneInfo("Asia/Jakarta")


class QRRequest(BaseModel):
    product_code: Literal["OVO", "JENIUS", "QRIS"] = Field(..., description="Gunakan 'QRIS' untuk QR")
    order_id: str = Field(..., min_length=1, max_length=20)
    amount: int = Field(..., ge=1, description="Jumlah tagihan (Rp, tanpa desimal)")
    customer_id: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=1, max_length=20)

    promo_code: Optional[str] = Field(None, max_length=64)
    is_sync: int = Field(0, ge=0, le=1, description="1=Sync, 0=Async (default 0)")
    branch_id: Optional[str] = Field(None, max_length=64)
    pos_id: Optional[str] = Field(None, max_length=64)


class QRResponse(BaseModel):
    qr_code: Optional[str] = None
    qr_link: Optional[str] = None


def now_str_jkt() -> str:
    return datetime.now(JKT).strftime("%Y-%m-%d %H:%M:%S")


def basic_auth_header(username: str, password: str) -> str:
    raw = f"{username}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def make_signature(rq_uuid: str, comm_code: str, product_code: str, order_id: str, amount: int, key: str) -> str:
    s = f"##{rq_uuid}##{comm_code}##{product_code}##{order_id}##{amount}##PUSHTOPAY##{key}##"
    return hashlib.sha256(s.upper().encode("utf-8")).hexdigest()


app = FastAPI(title="Espay QR Generator (Production)", version="1.0")


@app.post("/qr", response_model=QRResponse)
async def get_qr(req: QRRequest):
    if not (ESPAY_USERNAME and ESPAY_PASSWORD and ESPAY_COMM_CODE and ESPAY_SECRET_KEY):
        raise HTTPException(status_code=500, detail="Konfigurasi ESPAY_* belum lengkap")

    rq_uuid = uuid.uuid4().hex.upper()
    payload = {
        "rq_uuid": rq_uuid,
        "rq_datetime": now_str_jkt(),
        "comm_code": ESPAY_COMM_CODE,
        "product_code": req.product_code,
        "order_id": req.order_id,
        "amount": str(req.amount),
        "key": ESPAY_SECRET_KEY,
        "description": req.description,
        "customer_id": req.customer_id,
        "signature": make_signature(
            rq_uuid, ESPAY_COMM_CODE, req.product_code, req.order_id, req.amount, ESPAY_SECRET_KEY
        ),
    }

    if req.promo_code:
        payload["promo_code"] = req.promo_code
    payload["is_sync"] = str(req.is_sync)
    if req.branch_id:
        payload["branch_id"] = req.branch_id
    if req.pos_id:
        payload["pos_id"] = req.pos_id

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "Authorization": basic_auth_header(ESPAY_USERNAME, ESPAY_PASSWORD),
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0)) as client:
        try:
            r = await client.post(ESPAY_URL, data=payload, headers=headers)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Gagal hubungi Espay: {e}")

    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="Unauthorized dari Espay (Basic Auth salah)")
    if r.status_code >= 500:
        raise HTTPException(status_code=502, detail=f"Espay error {r.status_code}: {r.text}")

    try:
        data = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"Unexpected Espay response: {r.text}")

    return QRResponse(qr_code=data.get("QRCode"), qr_link=data.get("QRLink"))
