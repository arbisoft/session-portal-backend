from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify

from events.models import Event


@receiver(post_save, sender=Event)
def set_slug_on_create(_sender, instance, created, **kwargs):
    """
    Set a slug for the event instance if it is created and does not have a slug.
    The slug is generated from the title and includes the event ID to ensure uniqueness.
    """
    if created and not instance.slug:
        base_slug = slugify(instance.title)
        exists_with_title = Event.objects.filter(title=instance.title).exclude(pk=instance.pk).exists()

        if exists_with_title:
            slug = f"{base_slug}-{instance.id}"
        else:
            slug = base_slug

        instance.slug = slug
        instance.save(update_fields=['slug'])
