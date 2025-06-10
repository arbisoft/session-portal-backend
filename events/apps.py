from django.apps import AppConfig


class EventsConfig(AppConfig):
    """ Configuration for the events app """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'events'

    def ready(self):
        import events.signals  # pylint: disable=import-outside-toplevel, unused-import
