import requests
from django.conf import settings

def get_pesapal_token():
    url = f"{settings.PESAPAL_BASE_URL}/api/Auth/RequestToken"
    response = requests.post(url, json={
        "consumer_key": settings.PESAPAL_CONSUMER_KEY,
        "consumer_secret": settings.PESAPAL_CONSUMER_SECRET
    })
    response.raise_for_status()
    return response.json().get("token")

def get_payment_status(order_tracking_id):
    token = get_pesapal_token()
    headers = {
        "Authorization": f"Bearer {token}",
    }
    url = f"{settings.PESAPAL_BASE_URL}/api/Transactions/GetTransactionStatus?orderTrackingId={order_tracking_id}"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()





