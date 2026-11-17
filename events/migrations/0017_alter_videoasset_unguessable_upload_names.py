import pathlib

import django.core.files.storage
import django.core.validators
from django.db import migrations, models

import events.models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0016_alter_videoasset_caption_video_validators'),
    ]

    operations = [
        migrations.AlterField(
            model_name='videoasset',
            name='video_file',
            field=models.FileField(
                blank=True,
                null=True,
                storage=django.core.files.storage.FileSystemStorage(
                    base_url='/media/videos/',
                    location=pathlib.PurePosixPath('/app/arbisoft_sessions_portal/media/videos'),
                ),
                upload_to=events.models.unguessable_upload_name,
                validators=[
                    django.core.validators.FileExtensionValidator(
                        ['avi', 'mov', 'mp4', 'webm'],
                        message="Unsupported file type '.%(extension)s'. Allowed formats: %(allowed_extensions)s.",
                    )
                ],
            ),
        ),
        migrations.AlterField(
            model_name='videoasset',
            name='thumbnail',
            field=models.ImageField(
                blank=True,
                null=True,
                storage=django.core.files.storage.FileSystemStorage(
                    base_url='/media/thumbnails/',
                    location=pathlib.PurePosixPath('/app/arbisoft_sessions_portal/media/thumbnails'),
                ),
                upload_to=events.models.unguessable_upload_name,
            ),
        ),
    ]
