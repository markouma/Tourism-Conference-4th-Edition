import requests
import hmac
import hashlib
import time
import uuid
from urllib.parse import quote
from django.conf import settings
import base64
import json

def generate_pesapal_order(request, order_id, amount, email):
    try:
        # Convert amount to float
        amount = float(amount)
        
        # Generate OAuth 1.0 parameters
        oauth_nonce = str(uuid.uuid4()).replace('-', '')
        oauth_timestamp = str(int(time.time()))
        oauth_signature_method = "HMAC-SHA1"
        oauth_version = "1.0"
        
        # Base parameters
        params = {
            "oauth_consumer_key": settings.PESAPAL_CONFIG['CONSUMER_KEY'],
            "oauth_nonce": oauth_nonce,
            "oauth_signature_method": oauth_signature_method,
            "oauth_timestamp": oauth_timestamp,
            "oauth_version": oauth_version,
            "pesapal_request_data": json.dumps({
                "Amount": amount,
                "Description": "Event Ticket Purchase",
                "Type": "MERCHANT",
                "Reference": order_id,
                "FirstName": request.session['user_details']['name'].split()[0],
                "Email": email,
                "PhoneNumber": request.session['user_details']['phone'],
                "Currency": "KES",
                "CallbackURL": settings.PESAPAL_CONFIG['CALLBACK_URL']
            })
        }

        # Generate signature base string
        base_string = "&".join([
            "POST",
            quote(settings.PESAPAL_CONFIG['API_URL'], safe=''),
            quote("&".join([f"{k}={v}" for k, v in sorted(params.items())]), safe='')
        ])

        # Generate signing key
        signing_key = f"{settings.PESAPAL_CONFIG['CONSUMER_SECRET']}&"

        # Calculate signature
        signature = hmac.new(
            signing_key.encode(),
            base_string.encode(),
            hashlib.sha1
        ).digest()
        oauth_signature = base64.b64encode(signature).decode()

        # Add signature to params
        params['oauth_signature'] = oauth_signature

        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"OAuth oauth_consumer_key=\"{params['oauth_consumer_key']}\", " \
                            f"oauth_nonce=\"{params['oauth_nonce']}\", " \
                            f"oauth_signature=\"{quote(params['oauth_signature'])}\", " \
                            f"oauth_signature_method=\"{params['oauth_signature_method']}\", " \
                            f"oauth_timestamp=\"{params['oauth_timestamp']}\", " \
                            f"oauth_version=\"{params['oauth_version']}\""
        }

        # Send request
        response = requests.post(
            settings.PESAPAL_CONFIG['API_URL'],
            json=json.loads(params['pesapal_request_data']),
            headers=headers,
            timeout=30
        )

        print("\n=== PESAPAL REQUEST ===")
        print("URL:", settings.PESAPAL_CONFIG['API_URL'])
        print("Headers:", headers)
        print("Body:", params['pesapal_request_data'])
        print("\n=== PESAPAL RESPONSE ===")
        print("Status:", response.status_code)
        print("Response:", response.text)

        response.raise_for_status()
        return response.json()['redirect_url']

    except Exception as e:
        print(f"PESAPAL ERROR: {str(e)}")
        raise Exception(f"Failed to initiate Pesapal payment: {str(e)}")