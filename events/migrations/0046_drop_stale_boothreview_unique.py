from django.db import migrations


def drop_stale_unique(apps, schema_editor):
    """Drop the leftover UNIQUE(booth_id, reviewer_id) index on BoothReview.

    Migration 0002 created unique_together = ('booth', 'reviewer'). Migration
    0037 removed it from Django's model state only, because the production
    database had already drifted and no longer had the index - dropping it
    again there raised "Found wrong number (0) of constraints".

    On a database built fresh from these migrations the index really is there,
    so 0037 leaves state and schema disagreeing: the model allows a second
    review by the same reviewer, the database rejects it with an IntegrityError.

    This makes both cases converge. MySQL has no DROP INDEX IF EXISTS, so look
    the constraint up first and drop it only if it is actually present.
    """
    table = 'events_boothreview'
    columns = ['booth_id', 'reviewer_id']

    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(
            cursor, table
        )

        for name, info in constraints.items():
            if not info.get('unique'):
                continue
            # Leave primary keys and foreign keys alone - only the composite
            # unique index over exactly these two columns is stale.
            if info.get('primary_key') or info.get('foreign_key'):
                continue
            if list(info.get('columns') or []) != columns:
                continue

            cursor.execute(
                'ALTER TABLE %s DROP INDEX %s'
                % (schema_editor.quote_name(table), schema_editor.quote_name(name))
            )


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0045_documentcounter_invoicereceipt'),
    ]

    operations = [
        migrations.RunPython(drop_stale_unique, reverse_code=migrations.RunPython.noop),
    ]
