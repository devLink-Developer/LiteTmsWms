from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fulfillment", "0011_legacy_order_sync_cursor"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="fulfillmentorder",
            index=models.Index(fields=["legacy_sales_order_number", "-updated_at", "-created_at"], name="ful_order_so_recent_idx"),
        ),
        migrations.AddIndex(
            model_name="fulfillmentorder",
            index=models.Index(fields=["legacy_transaction_number", "-updated_at", "-created_at"], name="ful_order_tx_recent_idx"),
        ),
        migrations.AddIndex(
            model_name="fulfillmentorder",
            index=models.Index(fields=["customer_ref", "-updated_at", "-created_at"], name="ful_order_cust_recent_idx"),
        ),
    ]
