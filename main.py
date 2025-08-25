import uuid
import hashlib
import httpx
import base64
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional

# Konfigurasi Espay
ESPAY_PARTNER_ID = "SGWIKHSANPARFUM"  # Merchant Code dari Espay
ESPAY_MERCHANT_NAME = "IkhsanParfum"  # Merchant Name
ESPAY_API_KEY = "e1c30411e2c93716b23c83cc7de517e3"  # API Key untuk Generate Espay Embedded Script
ESPAY_SIGNATURE_KEY = "wp48y4qm9ur61495"  # Signature key
ESPAY_PASSWORD = "UFLDQRZQ"  # Password

# URL untuk berbagai service
ESPAY_SANDBOX_URL = "https://sandbox-api.espay.id/apimerchant/v1.0/debit/payment-host-to-host"
ESPAY_PRODUCTION_URL = "https://api.espay.id/apimerchant/v1.0/debit/payment-host-to-host"
ESPAY_VA_SANDBOX_URL = "https://sandbox-api.espay.id/rest/merchantpg/sendinvoice"
ESPAY_VA_PRODUCTION_URL = "https://api.espay.id/rest/merchantpg/sendinvoice"

# Alternative URLs berdasarkan dokumentasi
ESPAY_DIRECT_API_URL = "https://sandbox-api.espay.id/rest/merchantpg/directdebit"
ESPAY_SNAP_URL = "https://sandbox-api.espay.id/v2/transaction"

app = FastAPI(
    title="Espay Payment Integration",
    description="API untuk integrasi Virtual Account dan Payment Host to Host dengan Espay Payment Gateway",
    version="2.0.0"
)

# Pydantic Models
class AmountModel(BaseModel):
    value: str  # Format: "10000.00"
    currency: str = "IDR"

class UrlParamModel(BaseModel):
    url: str  # Thank you page URL
    type: str = "PAY_RETURN"
    isDeeplink: str = "N"

class PayOptionDetailsModel(BaseModel):
    payMethod: str  # Bank code (e.g., "014" for BCA)
    payOption: str  # Product code (e.g., "BCAATM")
    transAmount: AmountModel
    feeAmount: AmountModel

class AdditionalInfoModel(BaseModel):
    payType: str = "REDIRECT"  # REDIRECT, PAYLINK, S2BPAY
    userId: Optional[str] = None
    userName: Optional[str] = None
    userEmail: Optional[str] = None
    userPhone: Optional[str] = None
    buyerId: Optional[str] = None
    productCode: str  # e.g., "OVOLINK", "GOPAYLINK", "DANALINK"
    balanceType: Optional[str] = "CASH"
    bankCardToken: Optional[str] = None

class PaymentHostToHostRequest(BaseModel):
    partnerReferenceNo: Optional[str] = None
    amount: AmountModel
    urlParam: UrlParamModel
    validUpTo: Optional[str] = None
    pointOfInitiation: str = "Website"
    payOptionDetails: PayOptionDetailsModel
    additionalInfo: AdditionalInfoModel

class CreateVARequest(BaseModel):
    amount: str
    customer_name: str
    customer_phone: str
    customer_email: Optional[str] = None
    bank_code: str = "014"  # Default BCA
    va_expired_minutes: int = 60  # Default 60 menit
    order_id: Optional[str] = None

class SimplePaymentRequest(BaseModel):
    amount: str
    customer_name: str
    customer_email: str
    customer_phone: str
    bank_code: str = "014"
    thank_you_url: str = "https://yoursite.com/thank-you"
    payment_type: str = "redirect"

# Utility Functions
def generate_timestamp() -> str:
    """Generate timestamp dalam format ISO 8601"""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S+07:00")

def generate_external_id() -> str:
    """Generate unique external ID"""
    return str(uuid.uuid4())

def validate_amount_format(amount: str) -> bool:
    """Validasi format amount (harus dengan 2 digit desimal)"""
    try:
        float_amount = float(amount)
        return float_amount > 0 and "." in amount and len(amount.split(".")[1]) == 2
    except ValueError:
        return False

def format_amount(amount: float) -> str:
    """Format amount menjadi string dengan 2 digit desimal"""
    return f"{amount:.2f}"

def create_simple_signature(
    method: str,
    url: str, 
    timestamp: str,
    body: str,
    secret: str
) -> str:
    """
    Membuat signature sederhana untuk testing
    Format alternatif untuk debugging
    """
    try:
        string_to_sign = f"{method}|{url}|{timestamp}|{body}|{secret}"
        signature = hashlib.sha256(string_to_sign.encode('utf-8')).hexdigest()
        return base64.b64encode(signature.encode('utf-8')).decode('utf-8')
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error creating simple signature: {str(e)}"
        )

def create_va_signature(comm_code: str, order_id: str, amount: str, secret_key: str) -> str:
    """
    Membuat signature untuk Virtual Account
    Format: ##comm_code##order_id##amount##secret_key##
    """
    signature_plain_text = f"##{comm_code}##{order_id}##{amount}##{secret_key}##"
    hashed = hashlib.sha256(signature_plain_text.encode("utf-8")).hexdigest()
    return hashed

def get_pay_option_by_bank_code(bank_code: str) -> str:
    """Mapping bank code ke pay option"""
    bank_pay_options = {
        "008": "MANDIRIATM",
        "014": "BCAATM", 
        "016": "MAYBANKIDR",
        "009": "BNIATM",
        "002": "BRIATM",
        "011": "DANAMONATM"
    }
    return bank_pay_options.get(bank_code, "BCAATM")

def get_product_code_by_type(payment_type: str) -> str:
    """Get product code berdasarkan tipe pembayaran"""
    product_codes = {
        "gopay": "GOPAYLINK",
        "ovo": "OVOLINK", 
        "dana": "DANALINK",
        "shopeepay": "SHOPEEPAYLINK"
    }
    return product_codes.get(payment_type.lower(), "OVOLINK")

# API Endpoints
@app.post("/payment-host-to-host", response_model=dict, tags=["Payment Host to Host"])
async def create_payment_host_to_host(request: PaymentHostToHostRequest):
    """
    Membuat Payment Host to Host untuk redirect ke halaman checkout Espay
    """
    
    # Generate partner reference number jika tidak ada
    if not request.partnerReferenceNo:
        partner_reference_no = f"ORDER-{uuid.uuid4().hex[:12].upper()}"
    else:
        partner_reference_no = request.partnerReferenceNo
    
    # Validasi amount
    if not validate_amount_format(request.amount.value):
        raise HTTPException(
            status_code=400, 
            detail="Format amount harus dengan 2 digit desimal (contoh: 10000.00)"
        )
    
    # Generate timestamp dan external ID
    timestamp = generate_timestamp()
    external_id = generate_external_id()
    
    # Set validUpTo jika tidak ada (default 24 jam dari sekarang)
    if not request.validUpTo:
        valid_up_to = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S+07:00")
    else:
        valid_up_to = request.validUpTo
    
    # Siapkan request body
    request_body = {
        "partnerReferenceNo": partner_reference_no,
        "merchantId": ESPAY_PARTNER_ID,
        "subMerchantId": ESPAY_API_KEY,
        "amount": {
            "value": request.amount.value,
            "currency": request.amount.currency
        },
        "urlParam": {
            "url": request.urlParam.url,
            "type": request.urlParam.type,
            "isDeeplink": request.urlParam.isDeeplink
        },
        "validUpTo": valid_up_to,
        "pointOfInitiation": request.pointOfInitiation,
        "payOptionDetails": {
            "payMethod": request.payOptionDetails.payMethod,
            "payOption": request.payOptionDetails.payOption,
            "transAmount": {
                "value": request.payOptionDetails.transAmount.value,
                "currency": request.payOptionDetails.transAmount.currency
            },
            "feeAmount": {
                "value": request.payOptionDetails.feeAmount.value,
                "currency": request.payOptionDetails.feeAmount.currency
            }
        },
        "additionalInfo": {
            "payType": request.additionalInfo.payType,
            "userId": request.additionalInfo.userId,
            "userName": request.additionalInfo.userName,
            "userEmail": request.additionalInfo.userEmail,
            "userPhone": request.additionalInfo.userPhone,
            "buyerId": request.additionalInfo.buyerId,
            "productCode": request.additionalInfo.productCode,
            "balanceType": request.additionalInfo.balanceType,
            "bankCardToken": request.additionalInfo.bankCardToken
        }
    }
    
    # Remove None values from additionalInfo
    request_body["additionalInfo"] = {
        k: v for k, v in request_body["additionalInfo"].items() if v is not None
    }
    
    request_body_json = json.dumps(request_body, separators=(',', ':'))
    
    # Create signature dengan format yang disederhanakan untuk testing
    try:
        signature = create_simple_signature(
            method="POST",
            url=ESPAY_SANDBOX_URL,
            timestamp=timestamp,
            body=request_body_json,
            secret=ESPAY_SIGNATURE_KEY
        )
    except Exception as sig_error:
        print(f"⚠️ Signature error: {str(sig_error)}")
        # Fallback signature untuk testing
        signature = base64.b64encode(f"TEST_{timestamp}_{ESPAY_SIGNATURE_KEY}".encode()).decode()
    
    # Headers
    headers = {
        "Content-Type": "application/json",
        "X-TIMESTAMP": timestamp,
        "X-SIGNATURE": signature,
        "X-EXTERNAL-ID": external_id,
        "X-PARTNER-ID": ESPAY_PARTNER_ID,
        "CHANNEL-ID": "ESPAY",
        "Accept": "application/json"
    }
    
    print(f"🔹 Mengirim Payment Host to Host request:")
    print(f"   Merchant Code: {ESPAY_PARTNER_ID}")
    print(f"   Merchant Name: {ESPAY_MERCHANT_NAME}")
    print(f"   Partner Reference No: {partner_reference_no}")
    print(f"   Amount: {request.amount.value}")
    print(f"   Bank Code: {request.payOptionDetails.payMethod}")
    print(f"   Product Code: {request.additionalInfo.productCode}")
    print(f"   Timestamp: {timestamp}")
    print(f"   Signature: {signature[:50]}...")
    
    # Kirim request ke Espay
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                ESPAY_SANDBOX_URL,
                json=request_body,
                headers=headers
            )
            
            print(f"📡 Response Status: {response.status_code}")
            print(f"📡 Response Text: {response.text}")
            
            # Parse response
            try:
                response_data = response.json()
            except Exception as json_error:
                raise HTTPException(
                    status_code=500,
                    detail=f"Gagal parsing JSON response: {str(json_error)}"
                )
            
            # Cek response code
            response_code = response_data.get("responseCode", "")
            if not response_code.startswith("200"):
                error_message = response_data.get("responseMessage", "Unknown error")
                raise HTTPException(
                    status_code=400,
                    detail=f"Error dari Espay: {error_message} (Code: {response_code})"
                )
            
            return {
                "status": "success",
                "message": "Payment Host to Host berhasil dibuat",
                "data": {
                    "partner_reference_no": partner_reference_no,
                    "redirect_url": response_data.get("webRedirectUrl"),
                    "approval_code": response_data.get("approvalCode"),
                    "amount": request.amount.value,
                    "valid_up_to": valid_up_to
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
            raise
        except Exception as e:
            print(f"❌ Unexpected error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Terjadi kesalahan internal: {str(e)}"
            )

@app.post("/simple-payment", tags=["Payment Host to Host"])
async def create_simple_payment(request: SimplePaymentRequest):
    """
    Endpoint sederhana untuk membuat pembayaran Host to Host
    """
    
    # Validasi amount
    try:
        amount_float = float(request.amount)
        if amount_float <= 0:
            raise HTTPException(status_code=400, detail="Amount harus lebih besar dari 0")
        formatted_amount = format_amount(amount_float)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format amount tidak valid")
    
    # Calculate fee (contoh 2.5%)
    fee_amount = format_amount(amount_float * 0.025)
    
    # Build request
    payment_request = PaymentHostToHostRequest(
        amount=AmountModel(value=formatted_amount),
        urlParam=UrlParamModel(url=request.thank_you_url),
        payOptionDetails=PayOptionDetailsModel(
            payMethod=request.bank_code,
            payOption=get_pay_option_by_bank_code(request.bank_code),
            transAmount=AmountModel(value=formatted_amount),
            feeAmount=AmountModel(value=fee_amount)
        ),
        additionalInfo=AdditionalInfoModel(
            payType="REDIRECT" if request.payment_type.lower() == "redirect" else "PAYLINK",
            userName=request.customer_name,
            userEmail=request.customer_email,
            userPhone=request.customer_phone,
            productCode=get_product_code_by_type("ovo")  # Default OVO
        )
    )
    
    return await create_payment_host_to_host(payment_request)

@app.post("/create-va", response_model=dict, tags=["Virtual Account"])
async def create_virtual_account(request: CreateVARequest):
    """
    Membuat Virtual Account Espay (metode lama untuk compatibility)
    
    Bank Codes yang tersedia:
    - 008: Mandiri
    - 014: BCA  
    - 016: Maybank
    - 009: BNI
    - 002: BRI
    - 011: Danamon
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
    
    # Validasi nomor telepon
    phone = request.customer_phone.strip()
    if not phone.startswith(('0', '+62')):
        raise HTTPException(status_code=400, detail="Nomor telepon harus diawali dengan 0 atau +62")
    
    # Generate timestamp
    rq_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rq_uuid = str(uuid.uuid4())
    
    # Buat signature untuk VA
    signature = create_va_signature(
        comm_code=ESPAY_PARTNER_ID,
        order_id=order_id,
        amount=formatted_amount,
        secret_key=ESPAY_API_KEY
    )

    # Siapkan payload untuk VA
    payload = {
        "rq_uuid": rq_uuid,
        "rq_datetime": rq_datetime,
        "order_id": order_id,
        "amount": formatted_amount,
        "ccy": "IDR",
        "comm_code": ESPAY_PARTNER_ID,
        "remark1": phone,
        "remark2": request.customer_name,
        "remark3": request.customer_email or "",
        "update": "N",
        "bank_code": request.bank_code,
        "va_expired": str(request.va_expired_minutes),
        "signature": signature
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }

    print(f"🔹 Mengirim VA request ke ESPAY:")
    print(f"   Merchant Code: {ESPAY_PARTNER_ID}")
    print(f"   Order ID: {order_id}")
    print(f"   Amount: {formatted_amount}")
    print(f"   Bank Code: {request.bank_code}")
    print(f"   Signature: {signature[:50]}...")

    # Kirim request ke Espay VA endpoint
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                ESPAY_VA_SANDBOX_URL,
                data=payload,
                headers=headers
            )

            print(f"📡 VA Response Status: {response.status_code}")
            print(f"📡 VA Response Text: {response.text}")

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"HTTP error dari ESPAY VA: {response.text}"
                )

            try:
                response_data = response.json()
            except Exception as json_error:
                raise HTTPException(
                    status_code=500,
                    detail=f"Gagal parsing JSON response VA: {str(json_error)}"
                )

            # Cek error code dari Espay VA
            error_code = response_data.get("error_code", "")
            if error_code != "0000":
                error_message = response_data.get("error_message", "Unknown error")
                raise HTTPException(
                    status_code=400,
                    detail=f"Error dari Espay VA: {error_message} (Code: {error_code})"
                )

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

        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ VA Unexpected error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Terjadi kesalahan internal VA: {str(e)}"
            )

@app.post("/test-connection", tags=["Testing"])
async def test_espay_connection():
    """
    Test koneksi ke Espay untuk debugging
    """
    test_data = {
        "merchant_code": ESPAY_PARTNER_ID,
        "merchant_name": ESPAY_MERCHANT_NAME,
        "api_key": ESPAY_API_KEY[:10] + "...",
        "signature_key": ESPAY_SIGNATURE_KEY[:10] + "...",
        "timestamp": generate_timestamp(),
        "urls": {
            "host_to_host": ESPAY_SANDBOX_URL,
            "virtual_account": ESPAY_VA_SANDBOX_URL
        }
    }
    
    return {
        "status": "info",
        "message": "Informasi koneksi Espay",
        "data": test_data,
        "note": "Gunakan endpoint ini untuk mengecek konfigurasi sebelum melakukan transaksi"
    }

@app.post("/debug-signature", tags=["Testing"])
async def debug_signature(
    method: str = "POST",
    url: str = ESPAY_SANDBOX_URL,
    body: str = '{"test":"data"}',
    timestamp: str = None
):
    """
    Debug signature generation untuk troubleshooting
    """
    if not timestamp:
        timestamp = generate_timestamp()
    
    try:
        # Test berbagai format signature
        signatures = {}
        
        # Format 1: Simple
        string1 = f"{method}|{url}|{timestamp}|{body}|{ESPAY_SIGNATURE_KEY}"
        signatures["format_1_simple"] = {
            "string_to_sign": string1,
            "signature": hashlib.sha256(string1.encode()).hexdigest()
        }
        
        # Format 2: Colon separated  
        string2 = f"{method}:{url}:{body}:{timestamp}:{ESPAY_SIGNATURE_KEY}"
        signatures["format_2_colon"] = {
            "string_to_sign": string2,
            "signature": hashlib.sha256(string2.encode()).hexdigest()
        }
        
        # Format 3: Base64 encoded
        string3 = f"{method}:{url}:{body}:{timestamp}:{ESPAY_SIGNATURE_KEY}"
        sig3 = hashlib.sha256(string3.encode()).hexdigest()
        signatures["format_3_base64"] = {
            "string_to_sign": string3,
            "signature": base64.b64encode(sig3.encode()).decode()
        }
        
        return {
            "status": "debug",
            "message": "Signature debugging information",
            "data": {
                "inputs": {
                    "method": method,
                    "url": url,
                    "body": body,
                    "timestamp": timestamp,
                    "secret_key": ESPAY_SIGNATURE_KEY[:10] + "..."
                },
                "signatures": signatures
            }
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Debug signature error: {str(e)}"
        }

@app.post("/simple-va-alternative", tags=["Virtual Account"])
async def create_simple_va_alternative(
    amount: str,
    customer_name: str,
    customer_phone: str,
    customer_email: str = "",
    bank_code: str = "014"
):
    """
    Endpoint alternatif untuk VA dengan format yang disederhanakan
    """
    try:
        # Generate order ID
        order_id = f"VA-{uuid.uuid4().hex[:8].upper()}"
        
        # Format amount
        amount_float = float(amount)
        formatted_amount = f"{amount_float:.2f}"
        
        # Timestamp untuk VA
        rq_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rq_uuid = str(uuid.uuid4())
        
        # Signature untuk VA (format sederhana)
        signature_string = f"{ESPAY_PARTNER_ID}{order_id}{formatted_amount}{ESPAY_API_KEY}"
        signature = hashlib.sha256(signature_string.encode()).hexdigest()
        
        # Payload yang disederhanakan
        payload = {
            "rq_uuid": rq_uuid,
            "rq_datetime": rq_datetime,
            "order_id": order_id,
            "amount": formatted_amount,
            "ccy": "IDR",
            "comm_code": ESPAY_PARTNER_ID,
            "remark1": customer_phone,
            "remark2": customer_name,
            "remark3": customer_email,
            "update": "N",
            "bank_code": bank_code,
            "va_expired": "1440",  # 24 jam
            "signature": signature
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "Espay-Client/1.0"
        }
        
        print(f"🔹 Testing VA Alternative:")
        print(f"   URL: {ESPAY_VA_SANDBOX_URL}")
        print(f"   Order ID: {order_id}")
        print(f"   Amount: {formatted_amount}")
        print(f"   Signature String: {signature_string}")
        print(f"   Signature: {signature}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                ESPAY_VA_SANDBOX_URL,
                data=payload,
                headers=headers
            )
            
            print(f"📡 Response Status: {response.status_code}")
            print(f"📡 Response Headers: {dict(response.headers)}")
            print(f"📡 Response Text: {response.text}")
            
            try:
                response_data = response.json()
            except Exception:
                response_data = {"raw_response": response.text}
            
            return {
                "status": "test_response",
                "message": "Response dari Espay VA Alternative",
                "request_data": {
                    "url": ESPAY_VA_SANDBOX_URL,
                    "payload": payload,
                    "headers": headers
                },
                "response_data": {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": response_data
                }
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error in alternative VA: {str(e)}"
        }

@app.get("/bank-codes", tags=["Reference"])
def get_bank_codes():
    """Daftar bank codes yang tersedia untuk Payment Host to Host"""
    return {
        "status": "success",
        "data": {
            "bank_codes": {
                "008": {"name": "Bank Mandiri", "payOption": "MANDIRIATM"},
                "014": {"name": "Bank BCA", "payOption": "BCAATM"},
                "016": {"name": "Bank Maybank", "payOption": "MAYBANKIDR"},
                "009": {"name": "Bank BNI", "payOption": "BNIATM"},
                "002": {"name": "Bank BRI", "payOption": "BRIATM"},
                "011": {"name": "Bank Danamon", "payOption": "DANAMONATM"}
            },
            "product_codes": {
                "GOPAYLINK": "GoPay",
                "OVOLINK": "OVO",
                "DANALINK": "DANA",
                "SHOPEEPAYLINK": "ShopeePay"
            }
        }
    }

@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Espay Payment Integration",
        "timestamp": datetime.now().isoformat(),
        "merchant_code": ESPAY_PARTNER_ID,
        "merchant_name": ESPAY_MERCHANT_NAME
    }

@app.get("/", tags=["General"])
def read_root():
    """Root endpoint dengan informasi dasar"""
    return {
        "service": "Espay Payment Integration", 
        "version": "2.0.0",
        "status": "running",
        "merchant_info": {
            "merchant_code": ESPAY_PARTNER_ID,
            "merchant_name": ESPAY_MERCHANT_NAME
        },
        "endpoints": {
            "payment_host_to_host": "/payment-host-to-host",
            "simple_payment": "/simple-payment",
            "create_va": "/create-va", 
            "bank_codes": "/bank-codes",
            "health": "/health",
            "test_connection": "/test-connection",
            "debug_signature": "/debug-signature",
            "docs": "/docs"
        },
        "features": [
            "Payment Host to Host (Redirect to Espay Checkout)",
            "Virtual Account Creation (Direct VA Number)",
            "Multiple Bank Support",
            "Proper Error Handling"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)