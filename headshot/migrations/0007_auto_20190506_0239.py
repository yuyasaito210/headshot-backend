# Generated by Django 2.0.5 on 2019-05-06 02:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('headshot', '0006_auto_20190506_0125'),
    ]

    operations = [
        migrations.AlterField(
            model_name='headshot',
            name='doc_format',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
    ]
