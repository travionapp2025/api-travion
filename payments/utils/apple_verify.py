import time
import jwt
import base64
import json
import requests
from django.conf import settings
from cryptography import x509
from cryptography.hazmat.backends import default_backend


# --------------------------------
# Generate JWT for Apple StoreKit 2
# --------------------------------
def generate_apple_jwt():
    """
    Generates JWT token for Apple StoreKit 2 verification
    """
    try:
        key_id = settings.APPLE_KEY_ID
        issuer_id = settings.APPLE_ISSUER_ID
        private_key = settings.APPLE_PRIVATE_KEY

        if not all([key_id, issuer_id, private_key]):
            raise ValueError("Missing Apple JWT configuration")

        private_key = private_key.strip()

        headers = {
            "alg": "ES256",
            "kid": key_id,
            "typ": "JWT"
        }

        now = int(time.time())

        payload = {
            "iss": issuer_id,
            "iat": now,
            "exp": now + 900  # 15 minutes
        }

        token = jwt.encode(
            payload,
            private_key,
            algorithm="ES256",
            headers=headers
        )

        return token

    except Exception as e:
        # Do not crash server
        raise Exception("Failed to generate Apple JWT") from e



def verify_storekit2_receipt(receipt):
    """
    Verifies StoreKit 2 JWS receipt using x5c certificate chain
    Returns decoded payload (dict)
    """

    if not receipt or not isinstance(receipt, str):
        raise Exception("Invalid receipt format")

    # 1️⃣ Extract header safely
    try:
        header = jwt.get_unverified_header(receipt)
    except Exception:
        raise Exception("Invalid Apple receipt header")

    x5c_chain = header.get("x5c")
    if not x5c_chain or not isinstance(x5c_chain, list):
        raise Exception("Invalid Apple receipt: x5c missing")

    # 2️⃣ Load Apple public key from leaf certificate
    try:
        cert_b64 = x5c_chain[0]
        cert_der = base64.b64decode(cert_b64)

        cert = x509.load_der_x509_certificate(
            cert_der,
            default_backend()
        )
        public_key = cert.public_key()
    except Exception:
        raise Exception("Failed to parse Apple receipt certificate")

    # 3️⃣ Verify signature and decode payload
    try:
        decoded = jwt.decode(
            receipt,
            public_key,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise Exception("Apple receipt signature expired")
    except jwt.InvalidSignatureError:
        raise Exception("Invalid Apple receipt signature")
    except Exception:
        raise Exception("Failed to decode Apple receipt")

    if not isinstance(decoded, dict):
        raise Exception("Invalid Apple receipt payload")

    return decoded


def _verify_apple_receipt_data(receipt, use_sandbox=False):
    if not receipt or not isinstance(receipt, str):
        raise Exception("Invalid Apple receipt data")

    if not getattr(settings, "APPLE_SHARED_SECRET", None):
        raise Exception("Missing Apple shared secret")

    endpoint = (
        "https://sandbox.itunes.apple.com/verifyReceipt"
        if use_sandbox
        else "https://buy.itunes.apple.com/verifyReceipt"
    )

    payload = {
        "receipt-data": receipt,
        "password": settings.APPLE_SHARED_SECRET,
        "exclude-old-transactions": True,
    }

    response = requests.post(endpoint, json=payload, timeout=15)
    response.raise_for_status()
    return response.json()


def _lookup_apple_transaction(transaction_id, product_id=None, use_sandbox=False):
    if not transaction_id:
        raise Exception("Missing Apple transaction id for StoreKit lookup")

    jwt_token = generate_apple_jwt()
    endpoint = (
        "https://api.storekit.itunes.apple.com/inApps/v1/lookup"
        if not use_sandbox
        else "https://api.storekit-sandbox.itunes.apple.com/inApps/v1/lookup"
    )

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        endpoint,
        json={"transactionId": transaction_id},
        headers=headers,
        timeout=15,
    )

    if response.status_code != 200:
        raise Exception(
            f"Apple StoreKit lookup failed: {response.status_code} {response.text}"
        )

    payload = response.json()
    transaction_info = payload.get("transactionInfo") or payload.get("transaction") or payload

    if not isinstance(transaction_info, dict):
        raise Exception("Apple StoreKit lookup returned invalid transaction info")

    if product_id and transaction_info.get("productId") != product_id:
        raise Exception("Apple StoreKit lookup product_id mismatch")

    return transaction_info


def _find_apple_one_time_purchase(receipt_response, product_id=None, purchase_id=None):
    receipt = receipt_response.get("latest_receipt_info")
    if not receipt:
        receipt = receipt_response.get("receipt", {}).get("in_app", [])

    if not isinstance(receipt, list):
        return None

    for entry in reversed(receipt):
        if product_id and entry.get("product_id") != product_id:
            continue

        if purchase_id and purchase_id not in (
            entry.get("transaction_id"),
            entry.get("original_transaction_id"),
        ):
            continue

        if entry.get("cancellation_date") or entry.get("cancellation_date_ms"):
            continue

        return entry

    return None


def _is_incomplete_storekit_jwt(receipt):
    try:
        decoded = base64.urlsafe_b64decode(receipt + "=" * (-len(receipt) % 4))
        decoded_text = decoded.decode("utf-8")
        return decoded_text.strip().startswith("{\"alg\":") and "\"x5c\"" in decoded_text
    except Exception:
        return False


def verify_apple_one_time_product(product_id, receipt, purchase_id=None):
    """
    Verifies Apple one-time product (consumable/non-consumable) purchase.
    Supports StoreKit 2 signed transaction payloads and App Store receipt validation.
    Returns: (transaction_data, 'paid' if successful)
    """
    if not receipt or not isinstance(receipt, str):
        raise Exception("Invalid Apple receipt format")

    if _is_incomplete_storekit_jwt(receipt):
        raise Exception(
            "Apple receipt appears to be an incomplete StoreKit JWT header. "
            "Please send the full signed transaction string or a valid App Store receipt."
        )

    try:
        if "." in receipt:
            transaction_data = verify_storekit2_receipt(receipt)
            transaction_id = (
                transaction_data.get("transactionId")
                or transaction_data.get("originalTransactionId")
            )
            if not transaction_id:
                raise Exception("Invalid Apple transaction: missing transaction ID")
            return transaction_data, "paid"

        apple_response = _verify_apple_receipt_data(receipt)
        if apple_response.get("status") == 21007:
            apple_response = _verify_apple_receipt_data(receipt, use_sandbox=True)

        if apple_response.get("status") != 0:
            raise Exception(
                f"Apple receipt validation failed with status {apple_response.get('status')}"
            )

        purchase = _find_apple_one_time_purchase(
            apple_response,
            product_id=product_id,
            purchase_id=purchase_id,
        )

        if not purchase:
            raise Exception("No matching Apple purchase found in receipt")

        return purchase, "paid"

    except Exception as e:
        if purchase_id:
            try:
                return _lookup_apple_transaction(
                    purchase_id,
                    product_id=product_id,
                ), "paid"
            except Exception as lookup_error:
                try:
                    transaction_info = _lookup_apple_transaction(
                        purchase_id,
                        product_id=product_id,
                        use_sandbox=True,
                    )
                    return transaction_info, "paid"
                except Exception as sandbox_error:
                    raise Exception(
                        f"Apple one-time product verification failed: {str(e)}; "
                        f"StoreKit lookup fallback failed: {str(lookup_error)}; "
                        f"Sandbox lookup failed: {str(sandbox_error)}"
                    ) from e

        raise Exception(f"Apple one-time product verification failed: {str(e)}") from e
