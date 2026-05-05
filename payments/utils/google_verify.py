from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession
from django.conf import settings
from datetime import datetime, timezone as dt_timezone


def verify_google_subscription(
    package_name: str,
    subscription_id: str,
    purchase_token: str,
):
    """
    Verifies Google Play subscription
    Returns: (raw_response, expires_at, purchase_status)
    """

    try:
        if not all([package_name, subscription_id, purchase_token]):
            return None, None, "failed"

        credentials = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_PLAY_JSON_PATH,
            scopes=["https://www.googleapis.com/auth/androidpublisher"],
        )

        session = AuthorizedSession(credentials)

        url = (
            "https://androidpublisher.googleapis.com/androidpublisher/v3/"
            f"applications/{package_name}/purchases/subscriptions/"
            f"{subscription_id}/tokens/{purchase_token}"
        )

        response = session.get(url, timeout=10)

        # -----------------------
        # HTTP LEVEL ERRORS
        # -----------------------
        if response.status_code == 401:
            return None, None, "failed"

        if response.status_code == 404:
            return None, None, "failed"

        if response.status_code == 410:
            return None, None, "refunded"

        if response.status_code != 200:
            return None, None, "failed"

        # -----------------------
        # PARSE RESPONSE
        # -----------------------
        try:
            data = response.json()
        except Exception:
            return None, None, "failed"

        # -----------------------
        # EXPIRY TIME
        # -----------------------
        expiry_ms = data.get("expiryTimeMillis")
        if not expiry_ms:
            return data, None, "failed"

        try:
            expires_at = datetime.fromtimestamp(
                int(expiry_ms) / 1000,
                tz=dt_timezone.utc
            )
        except Exception:
            return data, None, "failed"

        payment_state = data.get("paymentState")
        cancel_reason = data.get("cancelReason")

        # -----------------------
        # STATUS MAPPING (IMPORTANT)
        # -----------------------
        if payment_state == 1:
            purchase_status = "active"
        elif payment_state == 0:
            purchase_status = "pending"
        else:
            purchase_status = "expired"

        # User cancelled subscription
        if cancel_reason is not None:
            purchase_status = "cancelled"

        # Expired by time
        if expires_at <= datetime.now(dt_timezone.utc):
            purchase_status = "expired"

        return data, expires_at, purchase_status

    except Exception:
        return None, None, "failed"


def cancel_google_subscription(
    package_name: str,
    subscription_id: str,
    purchase_token: str,
):
    try:
        if not all([package_name, subscription_id, purchase_token]):
            return False

        credentials = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_PLAY_JSON_PATH,
            scopes=["https://www.googleapis.com/auth/androidpublisher"],
        )

        session = AuthorizedSession(credentials)

        url = (
            "https://androidpublisher.googleapis.com/androidpublisher/v3/"
            f"applications/{package_name}/purchases/subscriptions/"
            f"{subscription_id}/tokens/{purchase_token}:cancel"
        )

        response = session.post(url, timeout=10)

        return response.status_code in (200, 204)

    except Exception:
        return False
