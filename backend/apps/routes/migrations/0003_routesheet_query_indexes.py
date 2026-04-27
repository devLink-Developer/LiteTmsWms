from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("routes", "0002_routesheet_driver_ref_routesheet_preview_payload_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="routesheet",
            index=models.Index(fields=["warehouse_ref", "planned_date", "status"], name="routesheet_wh_dt_st_idx"),
        ),
        migrations.AddIndex(
            model_name="routesheet",
            index=models.Index(fields=["driver_ref", "planned_date", "status"], name="routesheet_driver_dt_st_idx"),
        ),
    ]
