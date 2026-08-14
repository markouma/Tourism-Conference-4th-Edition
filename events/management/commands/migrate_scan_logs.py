from django.core.management.base import BaseCommand
from django.db import transaction
from events.models import TicketScanLog, ScanInstance, Event  # Replace 'your_app'


class Command(BaseCommand):
    help = 'Migrate existing scan logs to use scan instances'

    def handle(self, *args, **options):
        with transaction.atomic():
            events = Event.objects.all()
            total_migrated = 0
            
            for event in events:
                # Create default scan instance for this event
                default_instance, created = ScanInstance.objects.get_or_create(
                    name='General',
                    event=event,
                    defaults={
                        'description': 'Default scan instance for existing scans',
                        'is_active': True
                    }
                )
                
                if created:
                    self.stdout.write(f"Created default scan instance for {event.name}")
                
                # Find scan logs that need migration for this event
                # Adjust this query based on your ticket-event relationship
                scan_logs_to_migrate = TicketScanLog.objects.filter(
                    ticket__order__event=event,  # or ticket__staff_application__event=event
                    scan_instance__isnull=True
                )
                
                count = scan_logs_to_migrate.count()
                if count > 0:
                    scan_logs_to_migrate.update(scan_instance=default_instance)
                    total_migrated += count
                    self.stdout.write(f"Migrated {count} scan logs for {event.name}")
            
            self.stdout.write(
                self.style.SUCCESS(f'Successfully migrated {total_migrated} scan logs')
            )
