# Tourism Conference, 4th Edition

Django site for the Coast Tourism Conference, as deployed to thetourismconference.org.
Handles registrations, ticketing with QR codes, exhibitor booth sales, PDF invoices
and receipts, and payments through Pesapal and M-Pesa (Daraja).

Django 5.2 · Celery + Redis · MariaDB/MySQL · WeasyPrint for PDFs

## Setup

### Prerequisites

- Python 3.12+
- **MariaDB 10.5+** or **MySQL 8.0.11+**. Django 5.2 refuses to connect to
  anything older. Note that XAMPP still bundles MariaDB 10.4, which is too old;
  install a current server separately if that is what you have.
- For PDF generation only: WeasyPrint's native GTK/Pango libraries (see
  [PDF generation](#pdf-generation) below). The site runs without them.

```bash
git clone https://github.com/markouma/Tourism-Conference-4th-Edition.git
cd Tourism-Conference-4th-Edition

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create an empty database for it, since the app does not create one itself:

```sql
CREATE DATABASE tourismconference CHARACTER SET utf8mb4;
```

Then configure and run:

```bash
cp .env.example .env            # then fill it in, see below
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
`EMAIL_*` and `PESAPAL_*` / `DARAJA_*` keys can stay blank; you just won't be able
to send mail or take payments until you fill them in from your own accounts.

Two settings catch people out when running locally. `.env.example` already has both
set correctly, but if you write your own `.env`:

- `SECURE_SSL_REDIRECT=False`. Left at `True`, every `http://127.0.0.1:8000`
  request is redirected to `https://`, which nothing is serving, and the site looks
  like it is hanging.
- `BASE_URL`. Payment gateway callbacks are built from it, so Pesapal and Daraja
  must be able to reach it. `127.0.0.1` is fine for browsing the site, but to test
  payments point it at an ngrok (or similar) tunnel.

Geolocation of site visits uses a MaxMind GeoLite2 database at
`geoip/GeoLite2-City.mmdb`. It is not in the repo, because MaxMind restricts
redistribution. It is **optional**: without it the site runs normally and visits
are recorded without country and city. To enable it, get a free copy from
[MaxMind](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data) and put it at
that path.

## PDF generation

Tickets, invoices and receipts are rendered by WeasyPrint, which needs native
GTK/Pango libraries that `pip` cannot install:

- Debian/Ubuntu: `apt install libpango-1.0-0 libpangoft2-1.0-0`
- macOS: `brew install pango`
- Windows: install the GTK3 runtime, see the
  [WeasyPrint install docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)

Without them the site still starts and every page works; only PDF downloads
fail, with a message saying what to install. On a fresh Windows machine this is
the one thing `pip install -r requirements.txt` will not set up for you.

## Background jobs

Order reconciliation and email run on Celery, with Redis on `localhost:6379`:

```bash
celery -A tourismconference worker -l info
celery -A tourismconference beat -l info
```

Without these, payments still go through but pending orders won't reconcile
automatically.

## Apps

- `events`: registration, tickets, QR codes, payments, booths
- `controlpanel`: admin dashboard, reports, invoices and receipts
- `exhibitor_feedback`: post-event feedback and analytics

## Notes

- `requirements22.txt` is an older dependency set kept for reference. Use
  `requirements.txt`.
- Media uploads (QR codes, invoices) are only served by `runserver` when
  `DEBUG=True`. Behind a real web server, serve `MEDIA_ROOT` yourself.
- Run `python manage.py collectstatic` before deploying.
