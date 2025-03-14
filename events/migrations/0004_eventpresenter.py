# Generated by Django 4.2.16 on 2025-03-14 00:31

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('events', '0003_alter_videoasset_duration_alter_videoasset_file_size'),
    ]

    operations = [
        migrations.CreateModel(
            name='EventPresenter',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, related_name='presenters', to='events.event')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, related_name='events_presented', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
