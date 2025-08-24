import uuid
import hashlib
import httpx
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

# Konfigurasi Espay
ESPAY_COMM_CODE = "lantech001"  # Ganti dengan Merchant Code Anda
ESPAY_SECRET_KEY = "b393a0f80e6fc0fc6b88df85bd4678bd"
ESPAY_SANDBOX_URL = "https://sandbox-api.espay.id/rest/merchantpg/sendinvoice"
# ESPAY_PRODUCTION_URL = "https://api.espay.id/rest/merchantpg/sendinvoice"

app = FastAPI(
    title="Integrasi Espay Virtual Account",
    description="API untuk membuat Virtual Account menggunakan Espay Payment Gateway.",
    version="1.0.0"
)

class CreateVARequest(BaseModel):
    amount: str
    customer_name: str
    customer_phone: str
    customer_email: Optional[str] = None
    bank_code: str = "014"  # Default BCA
    va_expired_minutes: int = 60  # Default 60 menit
    order_id: Optional[str] = None

class EspayResponse(BaseModel):
    rq_uuid: str
    rs_datetime: str
    error_code: str
    error_message: str
    va_number: Optional[str] = None
    expired: Optional[str] = None
    description: Optional[str] = None
    total_amount: Optional[str] = None
    amount: Optional[str] = None
    fee: Optional[str] = None

def create_espay_signature(comm_code: str, order_id: str, amount: str, secret_key: str) -> str:
    """
    Membuat signature sesuai dokumentasi Espay
    Format: ##comm_code##order_id##amount##secret_key##
    """
    signature_plain_text = f"##{comm_code}##{order_id}##{amount}##{secret_key}##"
    hashed = hashlib.sha256(signature_plain_text.encode("utf-8")).hexdigest()
    return hashed

def validate_amount(amount: str) -> bool:
    """Validasi format amount (harus dengan 2 digit desimal)"""
    try:
        float_amount = float(amount)
        return float_amount > 0 and "." in amount and len(amount.split(".")[1]) == 2
    except:
        return False

def format_amount(amount: float) -> str:
    """Format amount menjadi string dengan 2 digit desimal"""
    return f"{amount:.2f}"

@app.post("/create-va", response_model=dict, tags=["Virtual Account"])
async def create_virtual_account(request: CreateVARequest):
    """
    Membuat Virtual Account Espay
    
    Bank Codes yang tersedia:
    - 008: Mandiri
    - 014: BCA  
    - 016: Maybank
    - 009: BNI
    - 002: BRI
    - 011: Danamon
    - 213: BTPN
    """
    
    # Generate order_id jika tidak disediakan
    if not request.order_id:
        order_id = f"INV-{uuid.uuid4().hex[:12].upper()}"
    else:
        order_id = request.order_id
    
    # Validasi dan format amount
    try:
        amount_float = float(request.amount)
        if amount_float <= 0:
            raise HTTPException(status_code=400, detail="Amount harus lebih besar dari 0")
        formatted_amount = format_amount(amount_float)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format amount tidak valid")
    
    # Validasi nomor telepon (harus diawali dengan 0 atau +62)
    phone = request.customer_phone.strip()
    if not phone.startswith(('0', '+62')):
        raise HTTPException(status_code=400, detail="Nomor telepon harus diawali dengan 0 atau +62")
    
    # Generate timestamp
    rq_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rq_uuid = str(uuid.uuid4())
    
    # Buat signature sesuai dokumentasi Espay
    signature = create_espay_signature(
        comm_code=ESPAY_COMM_CODE,
        order_id=order_id,
        amount=formatted_amount,
        secret_key=ESPAY_SECRET_KEY
    )

    # Siapkan payload sesuai dokumentasi Espay
    payload = {
        "rq_uuid": rq_uuid,
        "rq_datetime": rq_datetime,
        "order_id": order_id,
        "amount": formatted_amount,
        "ccy": "IDR",
        "comm_code": ESPAY_COMM_CODE,
        "remark1": phone,  # No handphone (mandatory untuk beberapa skema)
        "remark2": request.customer_name,  # Nama (mandatory)
        "remark3": request.customer_email or "",  # Email (optional)
        "update": "N",  # N untuk order_id baru
        "bank_code": request.bank_code,
        "va_expired": str(request.va_expired_minutes),
        "signature": signature
    }

    # Header sesuai dokumentasi
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*"
    }

    # Kirim request ke Espay
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"🔹 Mengirim request ke ESPAY:")
            print(f"   Order ID: {order_id}")
            print(f"   Amount: {formatted_amount}")
            print(f"   Bank Code: {request.bank_code}")
            print(f"   Signature: {signature}")
            
            response = await client.post(
                ESPAY_SANDBOX_URL,
                data=payload,
                headers=headers
            )

            # Log raw response untuk debugging
            print(f"📡 Raw Response Status: {response.status_code}")
            print(f"📡 Raw Response Text: {response.text}")

            # Cek HTTP status code
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"HTTP error dari ESPAY: {response.text}"
                )

            # Parse JSON response
            try:
                response_data = response.json()
            except Exception as json_error:
                raise HTTPException(
                    status_code=500,
                    detail=f"Gagal parsing JSON response: {str(json_error)}"
                )

            print(f"✅ Respons dari ESPAY: {response_data}")

            # Cek error code dari Espay
            error_code = response_data.get("error_code", "")
            if error_code != "0000":
                error_message = response_data.get("error_message", "Unknown error")
                raise HTTPException(
                    status_code=400,
                    detail=f"Error dari Espay: {error_message} (Code: {error_code})"
                )

            # Response sukses
            return {
                "status": "success",
                "message": "Virtual Account berhasil dibuat",
                "data": {
                    "order_id": order_id,
                    "va_number": response_data.get("va_number"),
                    "amount": response_data.get("amount"),
                    "total_amount": response_data.get("total_amount"),
                    "fee": response_data.get("fee"),
                    "expired": response_data.get("expired"),
                    "bank_code": request.bank_code,
                    "customer_name": request.customer_name,
                    "customer_phone": phone
                },
                "espay_response": response_data
            }

        except httpx.TimeoutException:
            raise HTTPException(
                status_code=408,
                detail="Request timeout ke ESPAY"
            )
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"HTTP error dari ESPAY: {e.response.text}"
            )
        except HTTPException:
            # Re-raise HTTPException agar tidak tertangkap oleh exception handler berikutnya
            raise
        except Exception as e:
            print(f"❌ Unexpected error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Terjadi kesalahan internal: {str(e)}"
            )

@app.get("/bank-codes", tags=["Reference"])
def get_bank_codes():
    """Menampilkan daftar bank code yang tersedia"""
    bank_codes = {
        "008": "Bank Mandiri",
        "014": "Bank BCA",
        "016": "Bank Maybank Indonesia",
        "009": "Bank BNI",
        "002": "Bank BRI",
        "011": "Bank Danamon",
        "213": "Bank BTPN"
    }
    return {
        "status": "success",
        "bank_codes": bank_codes,
        "note": "Gunakan code (key) saat membuat Virtual Account"
    }

@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "Espay VA Integration"
    }

@app.get("/", tags=["General"])
def read_root():
    """Root endpoint dengan informasi dasar"""
    return {
        "service": "Espay Virtual Account Integration",
        "status": "running",
        "docs_url": "/docs",
        "endpoints": {
            "create_va": "/create-va",
            "bank_codes": "/bank-codes",
            "health": "/health"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)