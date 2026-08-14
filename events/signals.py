from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

User = get_user_model()

@receiver(post_save, sender=User)
def link_guest_visits(sender, instance, created, **kwargs):
    if created:
        from django.apps import apps
        BoothVisit = apps.get_model("events", "BoothVisit")  # lazy load model

        visits = BoothVisit.objects.filter(
            visitor__isnull=True,
            guest_email=instance.email
        )
        if visits.exists():
            visits.update(visitor=instance)
