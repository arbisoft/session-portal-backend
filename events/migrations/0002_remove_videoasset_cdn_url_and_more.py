# Generated by Django 4.2.16 on 2025-01-24 02:30

import django.core.files.storage
from django.db import migrations, models
import pathlib


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='videoasset',
            name='cdn_url',
        ),
        migrations.RemoveField(
            model_name='videoasset',
            name='thumbnail_url',
        ),
        migrations.AddField(
            model_name='videoasset',
            name='thumbnail',
            field=models.ImageField(blank=True, null=True, storage=django.core.files.storage.FileSystemStorage(base_url='/media/thumbnails/', location=pathlib.PurePosixPath('/app/arbisoft_sessions_portal/media/thumbnails')), upload_to=''),
        ),
        migrations.AddField(
            model_name='videoasset',
            name='video_file',
            field=models.FileField(blank=True, null=True, storage=django.core.files.storage.FileSystemStorage(base_url='/media/videos/', location=pathlib.PurePosixPath('/app/arbisoft_sessions_portal/media/videos')), upload_to=''),
        ),
    ]
