from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession
from django.conf import settings


def verify_google_one_time_product(package_name: str, product_id: str, purchase_token: str):
    """
    Verifies a Google Play one-time product purchase via the Publisher API.
    Returns: (raw_response, status)  status: 'paid' | 'pending' | 'failed'
    """
    try:
        if not all([package_name, product_id, purchase_token]):
            return None, "failed"

        credentials = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_PLAY_JSON_PATH,
            scopes=["https://www.googleapis.com/auth/androidpublisher"],
        )
        session = AuthorizedSession(credentials)

        url = (
            "https://androidpublisher.googleapis.com/androidpublisher/v3/"
            f"applications/{package_name}/purchases/products/"
            f"{product_id}/tokens/{purchase_token}"
        )

        response = session.get(url, timeout=10)

        if response.status_code != 200:
            return None, "failed"

        data = response.json()
        # purchaseState: 0 = purchased, 1 = cancelled, 2 = pending
        state = data.get("purchaseState")
        if state == 0:
            return data, "paid"
        elif state == 2:
            return data, "pending"
        return data, "failed"

    except Exception:
        return None, "failed"
