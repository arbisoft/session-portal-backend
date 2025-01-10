from django.urls import path
from .views import EventTypeListView, EventsListView

urlpatterns = [
    path('event_types/', EventTypeListView.as_view(), name='event-type-list'),
    path('all/', EventsListView.as_view(), name='events-list')
]
