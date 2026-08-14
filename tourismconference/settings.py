from pathlib import Path
import os
from decouple import config, Csv
import pymysql
from dotenv import load_dotenv

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "reconcile-pending-orders-every-5-mins": {
        "task": "events.tasks.reconcile_pending_orders",
        "schedule": crontab(minute="*/5"),
    },
}

# Celery settings
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'



pymysql.install_as_MySQLdb()

BASE_DIR = Path(__file__).resolve().parent.parent



load_dotenv(dotenv_path=os.path.join(BASE_DIR, '.env'))

 
# Load secrets
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)


ALLOWED_HOSTS = ['thetourismconference.org', 'www.thetourismconference.org',
                 '127.0.0.1', 'localhost']
CSRF_TRUSTED_ORIGINS = [
    "https://thetourismconference.org",
    "https://www.thetourismconference.org",
]

BASE_URL = "https://thetourismconference.org/"
 
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'events',
    'controlpanel',
    'django_extensions',
    'exhibitor_feedback',
    'django.contrib.humanize',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
        "whitenoise.middleware.WhiteNoiseMiddleware", 
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.middleware.common.BrokenLinkEmailsMiddleware',
    'controlpanel.middleware.TrafficLoggerMiddleware',

    
        
]

ROOT_URLCONF = 'tourismconference.urls'


TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'tourismconference.wsgi.application'


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'),
        'PORT': config('DB_PORT'),
        'OPTIONS': {
            'ssl': {'ssl-disabled': True},
        }
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
LOCALE_PATHS = [os.path.join(BASE_DIR, 'locale')]
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
MEDIA_URL = '/media/'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
APPEND_SLASH = True

# Email
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'mail.thetourismconference.org'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False




EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='halloo@thetourismconference.org')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL='The 4th Conference <halloo@thetourismconference.org>'
EMAIL_SUBJECT_PREFIX = '[4thConf] '


# Pesapal
PESAPAL_CONFIG = {
    'CONSUMER_KEY': config('PESAPAL_CONSUMER_KEY'),
    'CONSUMER_SECRET': config('PESAPAL_CONSUMER_SECRET'),
    'AUTH_URL': config('PESAPAL_AUTH_URL'),
    'ORDER_URL': config('PESAPAL_ORDER_URL'),
    'CALLBACK_URL': f"{BASE_URL}/payment_callback/",
    'IPN_ID': config('PESAPAL_IPN_ID'),
    'ENVIRONMENT': config('PESAPAL_ENVIRONMENT'),
    "STATUS_URL": "https://pay.pesapal.com/v3/api/Transactions/GetTransactionStatus",    

}



# Daraja
DARAJA_CONFIG = {
    'CONSUMER_KEY': config('DARAJA_CONSUMER_KEY'),
    'CONSUMER_SECRET': config('DARAJA_CONSUMER_SECRET'),
    'SHORTCODE': config('DARAJA_SHORTCODE'),
    'PASSKEY': config('DARAJA_PASSKEY'),
    'INITIATE_URL': config('DARAJA_INITIATE_URL'),
    'TOKEN_URL': config('DARAJA_TOKEN_URL'),
    'CALLBACK_URL': f"{BASE_URL}/api/daraja/callback/",
    'ENVIRONMENT': config('DARAJA_ENVIRONMENT'),
}


# Security for production
SECURE_HSTS_SECONDS = 600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG


CSRF_COOKIE_HTTPONLY = False  # Allow JS to read the cookie
CSRF_COOKIE_SAMESITE = 'Lax'

X_FRAME_OPTIONS = 'SAMEORIGIN'  # Allows same-origin iframe embedding

# print("ALLOWED_HOSTS:", ALLOWED_HOSTS)   # noisy in the service log


# Inactivity timeout (in seconds)
SESSION_COOKIE_AGE = 86400  # 1 day
SESSION_SAVE_EVERY_REQUEST = True  # So it resets on every request
SESSION_COOKIE_HTTPONLY = True


# Set max POST body size to 25MB (adjust as needed)
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024  #25MB



LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
}



INSTALLED_APPS += ['channels']

ASGI_APPLICATION = 'tourismconference.asgi.application'

# Simple in-memory channel layer for dev
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}


# Booth cold-reservation  time in minutes
BOOTH_RESERVE_MINUTES = 10



RECAPTCHA_SITE_KEY = 'your-site-key'
RECAPTCHA_SECRET_KEY = 'your-secret-key'
SITE_URL = 'https://thetourismconference.org'
