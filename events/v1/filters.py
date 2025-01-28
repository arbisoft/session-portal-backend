import django_filters

from django.db.models import Q

from events.models import Event


class EventFilter(django_filters.rest_framework.FilterSet):
    """ Filter for the Event model """

    search = django_filters.CharFilter(method='filter_search')
    tag = django_filters.CharFilter(method='filter_tag')

    class Meta:
        model = Event
        fields = ('event_type', 'is_featured', 'status')

    def filter_search(self, queryset, _, value):
        """ Filter the queryset based on the search value """
        return queryset.filter(
            Q(title__icontains=value) |
            Q(description__icontains=value) |
            Q(creator__first_name__icontains=value) |
            Q(creator__last_name__icontains=value)
        )

    def filter_tag(self, queryset, _, value):
        """ Filter the queryset based on the tag value """
        return queryset.filter(
            tags__name=value
        )
