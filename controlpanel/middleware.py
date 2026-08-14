import geoip2.database
from django_user_agents.utils import get_user_agent
from .models import SiteVisit
from django.conf import settings

# Path to  GeoLite2 db
GEOIP_DB_PATH = 'geoip/GeoLite2-City.mmdb'
reader = geoip2.database.Reader(GEOIP_DB_PATH)

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
        try:
            response = reader.city(ip)
            country = response.country.name
            city = response.city.name
            return country, city
        except:
            return None, None


