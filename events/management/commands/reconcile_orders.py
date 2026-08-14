# payments/management/commands/reconcile_orders.py
from django.core.management.base import BaseCommand
from events.tasks import reconcile_pending_orders

class Command(BaseCommand):
    help = "Run pending orders reconciliation (use in cron if no Celery)"

    def handle(self, *args, **kwargs):
        reconcile_pending_orders()
        self.stdout.write(self.style.SUCCESS("reconcile_pending_orders invoked"))
