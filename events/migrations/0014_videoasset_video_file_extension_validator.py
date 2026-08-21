import django.core.files.storage
import django.core.validators
from django.db import migrations, models
import pathlib


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0013_videoasset_captions_file'),
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
                upload_to='',
                validators=[django.core.validators.FileExtensionValidator(['avi', 'mov', 'mp4', 'webm'])],
            ),
        ),
    ]
