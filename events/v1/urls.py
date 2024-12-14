from django.urls import path
from .views import EventTypeListView

urlpatterns = [
    path('event_types/', EventTypeListView.as_view(), name='event-type-list'),
]
