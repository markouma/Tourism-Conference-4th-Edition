from django.core.management.base import BaseCommand
from events.models import Ticket, BoothApplication, TicketCategory


class Command(BaseCommand):
    help = 'Update country and city for existing Booth Representative tickets'

    def handle(self, *args, **options):
        # Get the Booth Representative category
        try:
            boothrep_category = TicketCategory.objects.get(name="Booth Representative")
        except TicketCategory.DoesNotExist:
            self.stdout.write(self.style.ERROR('Booth Representative category not found'))
            return

        # Get all booth rep tickets
        booth_tickets = Ticket.objects.filter(category=boothrep_category)
        
        updated_count = 0
        not_found_count = 0

        for ticket in booth_tickets:
            # Find the corresponding booth application and representative
            # Match by email and company name
            applications = BoothApplication.objects.filter(
                company=ticket.company_name,
                status='approved'
            )
            
            rep_found = False
            for app in applications:
                for rep in app.representatives.all():
                    if rep.email == ticket.guest_email:
                        # Update the ticket with rep's country and city
                        ticket.country = rep.country
                        ticket.city = rep.city
                        ticket.save()
                        
                        updated_count += 1
                        rep_found = True
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'✅ Updated ticket {ticket.ticket_number} - {rep.name} ({rep.country}, {rep.city})'
                            )
                        )
                        break
                if rep_found:
                    break
            
            if not rep_found:
                not_found_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'⚠️  Could not find rep for ticket {ticket.ticket_number} - {ticket.guest_email}'
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'\n✅ Updated {updated_count} tickets'
            )
        )
        if not_found_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    f'⚠️  Could not find representatives for {not_found_count} tickets'
                )
            )