from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("fulfillment", "0009_reparto_query_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="FulfillmentOrderImpact",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.CharField(blank=True, max_length=120)),
                ("updated_by", models.CharField(blank=True, max_length=120)),
                ("source_system", models.CharField(default="litecore", max_length=40)),
                ("source_table", models.CharField(blank=True, max_length=120)),
                ("source_pk", models.CharField(blank=True, max_length=120)),
                ("source_version", models.CharField(blank=True, max_length=120)),
                ("source_hash", models.CharField(blank=True, max_length=128)),
                ("legacy_transaction_number", models.CharField(blank=True, max_length=60)),
                ("legacy_sales_order_number", models.CharField(blank=True, max_length=60)),
                ("legacy_line_id", models.CharField(blank=True, max_length=60)),
                ("legacy_line_rec_id", models.CharField(blank=True, max_length=60)),
                ("legacy_rec_id", models.CharField(blank=True, max_length=60)),
                ("item_ref", models.CharField(blank=True, max_length=60)),
                ("warehouse_ref", models.CharField(blank=True, max_length=80)),
                ("store_ref", models.CharField(blank=True, max_length=80)),
                ("impact_type", models.CharField(choices=[("annulment", "Anulacion"), ("return", "Devolucion")], max_length=20)),
                ("status", models.CharField(choices=[("pending", "Pendiente"), ("applied", "Aplicado")], default="pending", max_length=20)),
                ("impact_sales_order_number", models.CharField(blank=True, max_length=60)),
                ("impact_transaction_number", models.CharField(blank=True, max_length=60)),
                ("impact_date", models.DateTimeField(blank=True, null=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                (
                    "fulfillment",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="impacts", to="fulfillment.fulfillmentorder"),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["impact_type", "status"], name="fulfillmen_impact_f2a1c7_idx"),
                    models.Index(fields=["legacy_sales_order_number", "impact_type"], name="fulfillmen_legacy__fb508f_idx"),
                    models.Index(fields=["impact_sales_order_number"], name="fulfillmen_impact_7e826d_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("source_table", "source_pk"), name="ful_order_impact_source_uniq"),
                ],
            },
        ),
        migrations.CreateModel(
            name="FulfillmentOrderImpactLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.CharField(blank=True, max_length=120)),
                ("updated_by", models.CharField(blank=True, max_length=120)),
                ("source_system", models.CharField(default="litecore", max_length=40)),
                ("source_table", models.CharField(blank=True, max_length=120)),
                ("source_pk", models.CharField(blank=True, max_length=120)),
                ("source_version", models.CharField(blank=True, max_length=120)),
                ("source_hash", models.CharField(blank=True, max_length=128)),
                ("legacy_transaction_number", models.CharField(blank=True, max_length=60)),
                ("legacy_sales_order_number", models.CharField(blank=True, max_length=60)),
                ("legacy_line_id", models.CharField(blank=True, max_length=60)),
                ("legacy_line_rec_id", models.CharField(blank=True, max_length=60)),
                ("legacy_rec_id", models.CharField(blank=True, max_length=60)),
                ("item_ref", models.CharField(blank=True, max_length=60)),
                ("warehouse_ref", models.CharField(blank=True, max_length=80)),
                ("store_ref", models.CharField(blank=True, max_length=80)),
                ("quantity", models.DecimalField(decimal_places=6, max_digits=18)),
                ("applied_qty", models.DecimalField(decimal_places=6, default=0, max_digits=18)),
                ("uom", models.CharField(max_length=20)),
                (
                    "fulfillment_line",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="impact_lines", to="fulfillment.fulfillmentorderline"),
                ),
                ("impact", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="fulfillment.fulfillmentorderimpact")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["legacy_line_id"], name="fulfillmen_legacy__e44782_idx"),
                    models.Index(fields=["item_ref", "warehouse_ref"], name="fulfillmen_item_re_b21e0d_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("impact", "source_pk"), name="ful_order_impact_line_source_uniq"),
                ],
            },
        ),
    ]
