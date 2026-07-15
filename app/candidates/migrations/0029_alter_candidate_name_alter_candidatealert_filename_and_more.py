from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("candidates", "0028_migrate_target_comments_to_candidates"),
    ]

    operations = [
        migrations.AlterField(
            model_name="candidate",
            name="name",
            field=models.CharField(max_length=150),
        ),
        migrations.AlterField(
            model_name="candidatealert",
            name="filename",
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
        migrations.AlterField(
            model_name="candidatealert",
            name="reference",
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
    ]
