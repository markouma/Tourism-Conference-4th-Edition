from django.core.management.base import BaseCommand
from events.models import Booth, Event


class Command(BaseCommand):
    help = "Deletes all booths for ${event_name} and recreates B1 to B52 with price=1."

    def handle(self, *args, **kwargs):
        event_name = "THE 4TH UGANDA - KENYA COAST TOURISM CONFERENCE"

        try:
            event = Event.objects.get(name=event_name)
        except Event.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Event '{event_name}' does not exist."))
            return

        # Delete all booths for this event
        deleted_count, _ = Booth.objects.filter(event=event).delete()
        self.stdout.write(self.style.WARNING(
            f"🗑 Deleted {deleted_count} booths for '{event.name}'."
        ))

        # Create new B1 → B52 booths
        booths = [Booth(event=event, name=f"B{i}", price=2) for i in range(1, 51)]
        Booth.objects.bulk_create(booths)

        self.stdout.write(self.style.SUCCESS(
            f"✅ Created {len(booths)} booths for '{event.name}'."
        ))
