import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fulfillment", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeliveryDocument",
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
                ("document_number", models.CharField(max_length=60, unique=True)),
                ("document_type", models.CharField(choices=[("remito", "Remito")], default="remito", max_length=30)),
                ("status", models.CharField(choices=[("issued", "Emitido"), ("voided", "Anulado")], default="issued", max_length=30)),
                ("issued_at", models.DateTimeField()),
                ("customer_ref", models.CharField(max_length=80)),
                ("address_snapshot", models.JSONField(blank=True, default=dict)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("void_reason", models.TextField(blank=True)),
                ("delivery", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="documents", to="fulfillment.deliveryorder")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["delivery", "document_type"], name="fulfillment_deliver_07303f_idx"),
                    models.Index(fields=["legacy_sales_order_number"], name="fulfillment_legacy__d57a4d_idx"),
                    models.Index(fields=["issued_at"], name="fulfillment_issued__5e535f_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="DeliveryDocumentLine",
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
                ("uom", models.CharField(max_length=20)),
                ("delivery_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="document_lines", to="fulfillment.deliveryorderline")),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="fulfillment.deliverydocument")),
            ],
        ),
    ]
