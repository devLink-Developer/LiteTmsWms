from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fulfillment", "0005_reconcile_remitted_quantities"),
    ]

    operations = [
        migrations.AddField(
            model_name="deliverydocumentline",
            name="conversion_factor",
            field=models.DecimalField(decimal_places=6, default=1, max_digits=18),
        ),
        migrations.AddField(
            model_name="deliverydocumentline",
            name="delivery_unit_qty",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="deliverydocumentline",
            name="delivery_uom",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="deliverydocumentline",
            name="item_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="deliverydocumentline",
            name="planned_volume_m3",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="deliverydocumentline",
            name="planned_weight_kg",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="deliveryorderline",
            name="conversion_factor",
            field=models.DecimalField(decimal_places=6, default=1, max_digits=18),
        ),
        migrations.AddField(
            model_name="deliveryorderline",
            name="delivery_unit_qty",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="deliveryorderline",
            name="delivery_uom",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="deliveryorderline",
            name="item_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="deliveryorderline",
            name="planned_volume_m3",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="deliveryorderline",
            name="planned_weight_kg",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=18),
        ),
    ]
