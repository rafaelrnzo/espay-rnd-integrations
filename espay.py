import os
import uuid
import hashlib
import base64
from datetime import datetime
import zoneinfo
from typing import Literal
from fastapi.responses import JSONResponse
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import socket

ESPAY_USERNAME = os.getenv("ESPAY_USERNAME", "SGWTIEBYMIN")
ESPAY_PASSWORD = os.getenv("ESPAY_PASSWORD", "HSQANGFD")
ESPAY_COMM_CODE = os.getenv("ESPAY_COMM_CODE", "SGWTIEBYMIN")
ESPAY_SECRET_KEY = os.getenv("ESPAY_SECRET_KEY", "tqqj5107obb6ydga")
ESPAY_URL = os.getenv("ESPAY_URL", "https://api.espay.id/rest/digitalpay/pushtopay")

JKT = zoneinfo.ZoneInfo("Asia/Jakarta")


class QRRequest(BaseModel):
    product_code: Literal["OVO", "JENIUS", "QRIS"] = Field(...)
    order_id: str = Field(..., min_length=1, max_length=20)
    amount: int = Field(..., ge=1)
    customer_id: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=1, max_length=20)


class QRResponse(BaseModel):
    qr_code: str | None = None
    qr_link: str | None = None


def now_str_jkt() -> str:
    return datetime.now(JKT).strftime("%Y-%m-%d %H:%M:%S")


def basic_auth_header(username: str, password: str) -> str:
    raw = f"{username}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def make_signature(rq_uuid: str, comm_code: str, product_code: str, order_id: str, amount: int, key: str) -> str:
    rq_uuid = str(rq_uuid).strip()
    comm_code = str(comm_code).strip()
    product_code = str(product_code).strip()
    order_id = str(order_id).strip()
    amount_str = str(int(amount))
    raw = f"##{rq_uuid}##{comm_code}##{product_code}##{order_id}##{amount_str}##PUSHTOPAY##{key}##"
    return hashlib.sha256(raw.upper().encode("utf-8")).hexdigest()


def resolve_debug(host: str):
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        return [{"family": i[0], "ip": i[4][0]} for i in infos]
    except Exception as e:
        return [{"error": str(e)}]


app = FastAPI(title="Espay QR Generator", version="1.0")


@app.post("/qr", response_model=QRResponse)
async def get_qr(req: QRRequest):
    if not (ESPAY_USERNAME and ESPAY_PASSWORD and ESPAY_COMM_CODE and ESPAY_SECRET_KEY):
        raise HTTPException(status_code=500, detail="Konfigurasi ESPAY_* belum lengkap")

    rq_uuid = uuid.uuid4().hex.upper()
    signature = make_signature(
        rq_uuid=rq_uuid,
        comm_code=ESPAY_COMM_CODE,
        product_code=req.product_code,
        order_id=req.order_id,
        amount=req.amount,
        key=ESPAY_SECRET_KEY,
    )

    payload = {
        "rq_uuid": rq_uuid,
        "rq_datetime": now_str_jkt(),
        "comm_code": ESPAY_COMM_CODE,
        "order_id": req.order_id.strip(),
        "product_code": req.product_code.strip(),
        "amount": str(int(req.amount)),
        "customer_id": req.customer_id.strip(),
        "description": req.description.strip(),
        "signature": signature,
    }

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
        raise HTTPException(status_code=401, detail="Unauthorized dari Espay")
    if r.status_code >= 500:
        raise HTTPException(status_code=502, detail=f"Espay error {r.status_code}: {r.text}")

    try:
        data = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"Unexpected Espay response: {r.text}")

    return JSONResponse(content=data)


@app.get("/_health")
async def health():
    dns_prod = resolve_debug("api.espay.id")
    dns_sbox = resolve_debug("sandbox-api.espay.id")
    async with httpx.AsyncClient(timeout=10.0) as c:
        try:
            egress_ip4 = (await c.get("https://api.ipify.org")).text
        except Exception as e:
            egress_ip4 = f"error: {e}"
        try:
            egress_ip6 = (await c.get("https://api6.ipify.org")).text
        except Exception as e:
            egress_ip6 = f"error: {e}"
    return {
        "time_jkt": now_str_jkt(),
        "espay_url": ESPAY_URL,
        "dns_prod": dns_prod,
        "dns_sandbox": dns_sbox,
        "egress_ip_v4": egress_ip4,
        "egress_ip_v6": egress_ip6,
    }
