# Generated by Django 4.2.16 on 2025-05-16 03:49

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0006_alter_event_playlists_alter_playlist_description_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='videoasset',
            name='event',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='videos', to='events.event'),
        ),
    ]
