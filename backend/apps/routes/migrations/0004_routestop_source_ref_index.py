from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("routes", "0003_routesheet_query_indexes"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="routestop",
            index=models.Index(fields=["source_type", "source_ref"], name="routestop_source_ref_idx"),
        ),
    ]
