# Tourism Conference — 4th Edition

Django site for the Coast Tourism Conference, as deployed to thetourismconference.org.
Handles registrations, ticketing with QR codes, exhibitor booth sales, PDF invoices
and receipts, and payments through Pesapal and M-Pesa (Daraja).

Django 5.2 · Celery + Redis · MariaDB/MySQL · WeasyPrint for PDFs

## Setup

You need Python 3.12+ and a running MariaDB or MySQL server.

```bash
git clone https://github.com/markouma/Tourism-Conference-4th-Edition.git
cd Tourism-Conference-4th-Edition

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create an empty database for it — the app does not create one itself:

```sql
CREATE DATABASE tourismconference CHARACTER SET utf8mb4;
```

Then configure and run:

```bash
cp .env.example .env            # then fill it in — see below
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The site comes up empty: create an event in `/admin/` before the public pages
have anything to show.

## Configuration

Every credential is read from `.env`; nothing is hardcoded. `.env.example` is
commented throughout, and its defaults are set up for local development.

Only `SECRET_KEY` and the `DB_*` values are required to get the site running. The
`EMAIL_*` and `PESAPAL_*` / `DARAJA_*` keys can stay blank — you just won't be able
to send mail or take payments until you fill them in from your own accounts.

Two settings catch people out when running locally. `.env.example` already has both
set correctly, but if you write your own `.env`:

- `SECURE_SSL_REDIRECT=False` — left at `True`, every `http://127.0.0.1:8000`
  request is redirected to `https://`, which nothing is serving, and the site looks
  like it is hanging.
- `BASE_URL` — payment gateway callbacks are built from it, so Pesapal and Daraja
  must be able to reach it. `127.0.0.1` is fine for browsing the site, but to test
  payments point it at an ngrok (or similar) tunnel.

Geolocation of site visits uses a MaxMind GeoLite2 database at
`geoip/GeoLite2-City.mmdb`. It is not in the repo, because MaxMind restricts
redistribution. It is **optional** — without it the site runs normally and visits
are recorded without country and city. To enable it, get a free copy from
[MaxMind](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data) and put it at
that path.

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
- Media uploads (QR codes, invoices) are only served by `runserver` when
  `DEBUG=True`. Behind a real web server, serve `MEDIA_ROOT` yourself.
- Run `python manage.py collectstatic` before deploying.
