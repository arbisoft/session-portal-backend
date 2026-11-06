import django.core.files.storage
import django.core.validators
from django.db import migrations, models
import pathlib


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0015_add_upload_session'),
    ]

    operations = [
        migrations.AlterField(
            model_name='videoasset',
            name='captions_file',
            field=models.FileField(
                blank=True,
                null=True,
                storage=django.core.files.storage.FileSystemStorage(
                    base_url='/media/captions/',
                    location=pathlib.PurePosixPath('/app/arbisoft_sessions_portal/media/captions'),
                ),
                upload_to='',
                validators=[django.core.validators.FileExtensionValidator(['vtt', 'srt'])],
            ),
        ),
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
                upload_to='',
                validators=[
                    django.core.validators.FileExtensionValidator(
                        ['avi', 'mov', 'mp4', 'webm'],
                        message="Unsupported file type '.%(extension)s'. Allowed formats: %(allowed_extensions)s.",
                    )
                ],
            ),
        ),
    ]
