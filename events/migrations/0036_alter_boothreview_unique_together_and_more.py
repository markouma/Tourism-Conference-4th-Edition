from django.db import migrations, models
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid

def generate_public_tokens(apps, schema_editor):
    Booth = apps.get_model('events', 'Booth')
    db_alias = schema_editor.connection.alias
    for booth in Booth.objects.using(db_alias).all():
        while True:
            new_uuid = uuid.uuid4()
            if not Booth.objects.using(db_alias).filter(public_token=new_uuid).exists():
                booth.public_token = new_uuid
                booth.save()
                break

class Migration(migrations.Migration):
    dependencies = [
        ('events', '0035_paidapplication_amount_paidapplication_mpesa_message_and_more'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.AddField(
            model_name='Booth',
            name='public_token',
            field=models.UUIDField(default=None, editable=False, unique=True, null=True),
        ),
        migrations.RunPython(generate_public_tokens, reverse_code=migrations.RunPython.noop),
        migrations.RunSQL(
            """
            ALTER TABLE events_booth
            MODIFY COLUMN public_token CHAR(36) NOT NULL;
            ALTER TABLE events_booth
            ADD CONSTRAINT events_booth_public_token_unique UNIQUE (public_token);
            """,
            reverse_sql="""
            ALTER TABLE events_booth
            DROP INDEX events_booth_public_token_unique;
            ALTER TABLE events_booth
            MODIFY COLUMN public_token CHAR(36);
            """,
        ),
        migrations.AddField(
            model_name='Booth',
            name='public_qr_code',
            field=models.ImageField(blank=True, null=True, upload_to='new_booth_QRs/'),
        ),
        migrations.RunSQL(
            """
            ALTER TABLE events_boothvisit
            DROP INDEX events_boothvisit_booth_id_visitor_id_ebff7189_uniq;
            """,
            reverse_sql="""
            ALTER TABLE events_boothvisit
            ADD CONSTRAINT events_boothvisit_booth_id_visitor_id_ebff7189_uniq
            UNIQUE (booth_id, visitor_id);
            """,
        ),
        migrations.AddField(
            model_name='BoothReview',
            name='ip_address',
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='BoothReview',
            name='reviewer',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                to='auth.User',
            ),
        ),
        migrations.AlterField(
            model_name='BoothReview',
            name='rating',
            field=models.PositiveSmallIntegerField(
                validators=[MinValueValidator(1), MaxValueValidator(5)]
            ),
        ),
    ]