from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fulfillment", "0007_alter_deliverydocument_status_deliveryexecution"),
    ]

    operations = [
        migrations.AddField(
            model_name="fulfillmentorder",
            name="address_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
