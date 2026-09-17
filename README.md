# Tourism Conference — 4th Edition

Django site for the Coast Tourism Conference, as deployed to thetourismconference.org.
Handles registrations, ticketing with QR codes, exhibitor booth sales, PDF invoices
and receipts, and payments through Pesapal and M-Pesa (Daraja).

Django 5.2 · Celery + Redis · MariaDB/MySQL · WeasyPrint for PDFs

## Setup

```bash
git clone https://github.com/markouma/Tourism-Conference-4th-Edition.git
cd Tourism-Conference-4th-Edition

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install geoip2 django-user-agents

cp .env.example .env            # then fill it in — see below
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Configuration

Every credential is read from `.env`; nothing is hardcoded. Copy `.env.example`
and fill in all of it — `SECRET_KEY`, the `DB_*` and `EMAIL_HOST_*` values, and the
`PESAPAL_*` / `DARAJA_*` keys from your gateway dashboards.

You also need a MaxMind GeoLite2 database at `geoip/GeoLite2-City.mmdb`. It isn't in
the repo (MaxMind restricts redistribution) and the site will not start without it —
`controlpanel/middleware.py` opens it at import time. Get a free one from
[MaxMind](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data).

## Background jobs

Order reconciliation and email run on Celery, with Redis on `localhost:6379`:

```bash
celery -A tourismconference worker -l info
celery -A tourismconference beat -l info
```

Without these, payments still go through but pending orders won't reconcile
automatically.

## Apps

- `events` — registration, tickets, QR codes, payments, booths
- `controlpanel` — admin dashboard, reports, invoices and receipts
- `exhibitor_feedback` — post-event feedback and analytics

## Notes

- `requirements22.txt` is an older dependency set kept for reference. Use
  `requirements.txt`.
- Run `python manage.py collectstatic` before deploying.
