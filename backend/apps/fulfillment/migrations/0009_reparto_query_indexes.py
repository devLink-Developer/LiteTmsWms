from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fulfillment", "0008_fulfillmentorder_address_snapshot"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="fulfillmentorder",
            index=models.Index(fields=["warehouse_ref", "status", "requested_date"], name="ful_order_wh_st_req_idx"),
        ),
        migrations.AddIndex(
            model_name="fulfillmentorder",
            index=models.Index(fields=["delivery_mode", "status", "requested_date"], name="ful_order_mode_st_req_idx"),
        ),
        migrations.AddIndex(
            model_name="deliveryorder",
            index=models.Index(fields=["warehouse_ref", "status", "planned_date"], name="ful_deliv_wh_st_dt_idx"),
        ),
        migrations.AddIndex(
            model_name="deliveryorder",
            index=models.Index(fields=["delivery_mode", "status", "planned_date"], name="ful_deliv_mode_st_dt_idx"),
        ),
    ]
