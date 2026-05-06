from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("fulfillment", "0010_fulfillment_order_impacts"),
    ]

    operations = [
        migrations.CreateModel(
            name="LegacyOrderSyncCursor",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.CharField(blank=True, max_length=120)),
                ("updated_by", models.CharField(blank=True, max_length=120)),
                ("name", models.CharField(max_length=120, unique=True)),
                ("last_modified_datetime", models.DateTimeField(blank=True, null=True)),
                ("last_source_pk", models.CharField(blank=True, max_length=120)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["name"], name="fulfillmen_name_6aa941_idx"),
                    models.Index(fields=["last_modified_datetime", "last_source_pk"], name="fulfillmen_last_mo_82c92d_idx"),
                ],
            },
        ),
    ]
