import time
import jwt
import base64
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
            "exp": now + 15777000  # ~6 months
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
