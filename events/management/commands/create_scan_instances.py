# Create this file: events/management/commands/create_scan_instances.py

from django.core.management.base import BaseCommand
from django.db import transaction
from events.models import Event, ScanInstance

class Command(BaseCommand):
    help = 'Create additional scan instances for events'

    def add_arguments(self, parser):
        parser.add_argument(
            '--event-id',
            type=int,
            help='Create instances for specific event ID',
        )
        parser.add_argument(
            '--instances',
            nargs='+',
            default=['Entrance', 'Meals 1', 'Meals 2', 'Registration'],
            help='List of scan instance names to create',
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            if options['event_id']:
                try:
                    event = Event.objects.get(id=options['event_id'])
                    events = [event]
                    self.stdout.write(f"Creating instances for event: {event.name}")
                except Event.DoesNotExist:
                    self.stderr.write(f"Event with ID {options['event_id']} not found")
                    return
            else:
                events = Event.objects.all()
                self.stdout.write(f"Creating instances for all {events.count()} events")
            
            total_created = 0
            instance_names = options['instances']
            
            for event in events:
                created_for_event = 0
                
                for instance_name in instance_names:
                    scan_instance, created = ScanInstance.objects.get_or_create(
                        name=instance_name,
                        event=event,
                        defaults={
                            'description': f'{instance_name} checkpoint for {event.name}',
                            'is_active': True
                        }
                    )
                    
                    if created:
                        created_for_event += 1
                        total_created += 1
                        self.stdout.write(f"  ✓ Created: {instance_name}")
                    else:
                        self.stdout.write(f"  - Exists: {instance_name}")
                
                self.stdout.write(f"Event '{event.name}': {created_for_event} new instances created")
                self.stdout.write("-" * 50)
            
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created {total_created} scan instances')
            )