import geoip2.database
from django_user_agents.utils import get_user_agent
from .models import SiteVisit
from django.conf import settings

import logging

logger = logging.getLogger(__name__)

# Path to  GeoLite2 db. Absolute, so manage.py works from any directory.
# MaxMind restricts redistribution, so the file is not in the repo - see README.
# Without it the site still runs, visits are just logged without country/city.
GEOIP_DB_PATH = settings.BASE_DIR / 'geoip' / 'GeoLite2-City.mmdb'

try:
    reader = geoip2.database.Reader(str(GEOIP_DB_PATH))
except (OSError, ValueError) as exc:
    logger.warning(
        "GeoLite2 database unavailable at %s (%s) - visits will be logged "
        "without geolocation.", GEOIP_DB_PATH, exc,
    )
    reader = None

INTERNAL_IPS = ['127.0.0.1', '192.168.X.X']

class TrafficLoggerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Skip admin, controlpanel, and internal IPs
        if request.path.startswith('/admin/') or request.path.startswith('/controlpanel/'):
            return response

        ip = self.get_client_ip(request)
        if ip in INTERNAL_IPS:
            return response

        user_agent = get_user_agent(request)
        # Skip bots/crawlers
        if user_agent.is_bot:
            return response

        # Get location
        country, city = self.get_location(ip)

        # Log visit
        SiteVisit.objects.create(
            ip_address=ip,
            user_agent=str(user_agent),
            path=request.path,
            country=country,
            city=city,
            referrer=request.META.get('HTTP_REFERER', ''),
            device_type='Mobile' if user_agent.is_mobile else 'Tablet' if user_agent.is_tablet else 'PC'
        )

        return response

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    def get_location(self, ip):
        if reader is None:
            return None, None
        try:
            response = reader.city(ip)
            country = response.country.name
            city = response.city.name
            return country, city
        except:
            return None, None


