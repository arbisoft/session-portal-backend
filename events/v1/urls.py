from django.urls import path

from .views import EventsListView, EventTypeListView, TagListView

urlpatterns = [
    path('event_types/', EventTypeListView.as_view(), name='event-type-list'),
    path('all/', EventsListView.as_view(), name='events-list'),
    path('tags/', TagListView.as_view(), name='tag-list')
]
