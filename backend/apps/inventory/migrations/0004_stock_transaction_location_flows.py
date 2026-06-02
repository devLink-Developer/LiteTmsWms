from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0003_reservation_line_locations"),
    ]

    operations = [
        migrations.AddField(
            model_name="inventoryledgerentry",
            name="lot_ref",
            field=models.CharField(blank=True, default="", max_length=80),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="inventorytransformationline",
            name="location_ref",
            field=models.CharField(blank=True, default="", max_length=120),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="inventorytransformationline",
            name="lot_ref",
            field=models.CharField(blank=True, default="", max_length=80),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="purchaseorderreceiptline",
            name="location_ref",
            field=models.CharField(blank=True, default="", max_length=120),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="purchaseorderreceiptline",
            name="lot_ref",
            field=models.CharField(blank=True, default="", max_length=80),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="inventoryledgerentry",
            name="movement_type",
            field=models.CharField(
                choices=[
                    ("inbound_receipt", "Ingreso por recepcion"),
                    ("reservation_hold", "Reserva"),
                    ("reservation_release", "Liberacion de reserva"),
                    ("pick", "Preparacion"),
                    ("dispatch", "Despacho"),
                    ("transfer_out", "Salida transferencia"),
                    ("transfer_in", "Entrada transferencia"),
                    ("adjustment", "Ajuste"),
                    ("transformation_in", "Transformacion entrada"),
                    ("transformation_out", "Transformacion salida"),
                    ("location_transfer", "Movimiento entre posiciones"),
                    ("write_off", "Baja de inventario"),
                    ("reversal", "Reversa"),
                ],
                max_length=40,
            ),
        ),
    ]
