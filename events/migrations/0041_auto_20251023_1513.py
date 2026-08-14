from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('events', '0040_auto_20251023_1456'),
    ]

    operations = [
        migrations.AddField(
            model_name='BoothReview',
            name='name',
            field=models.CharField(max_length=150, blank=True, null=True),
        ),
        migrations.AddField(
            model_name='BoothReview',
            name='email',
            field=models.EmailField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='BoothReview',
            name='phone_number',
            field=models.CharField(max_length=20, blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name='BoothReview',
            index=models.Index(fields=['booth', 'email'], name='booth_email_idx'),
        ),
    ]