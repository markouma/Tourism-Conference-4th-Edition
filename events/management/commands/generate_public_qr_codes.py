from django.core.management.base import BaseCommand
from django.conf import settings
from events.models import Booth
import qrcode
from io import BytesIO
from django.core.files import File
import os

class Command(BaseCommand):
    help = 'Generates public review QR codes for booths (updates public_qr_code only)'

    def handle(self, *args, **options):
        booths = Booth.objects.all()
        if not booths:
            self.stdout.write(self.style.WARNING('No booths found.'))
            return

        for booth in booths:
            if not booth.public_token:
                self.stdout.write(self.style.WARNING(f'Skipping booth {booth.id}: No public_token'))
                continue

            qr_data = f"{settings.SITE_URL}/review/booth/{booth.public_token}/"
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(qr_data)
            qr.make(fit=True)
            qr_image = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            qr_image.save(buffer, format='PNG')
            buffer.seek(0)
            filename = f'booth_{booth.id}_public_qr.png'

            if booth.public_qr_code:
                try:
                    old_path = os.path.join(settings.MEDIA_ROOT, booth.public_qr_code.name)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except FileNotFoundError:
                    pass

            booth.public_qr_code.save(filename, File(buffer), save=False)
            booth.save(update_fields=['public_qr_code'])
            buffer.close()

            self.stdout.write(self.style.SUCCESS(f'Generated public QR code for booth {booth.id}: {filename}'))