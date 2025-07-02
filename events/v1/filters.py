import django_filters

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Exists, OuterRef, Q, Value
from django.db.models.functions import Concat

from events.models import Event, EventPresenter, Playlist, Tag


class EventFilter(django_filters.rest_framework.FilterSet):
    """ Filter for the Event model """

    search = django_filters.CharFilter(method='filter_search')
    tag = django_filters.CharFilter(method='filter_tag')
    playlist = django_filters.CharFilter(method='filter_playlist')
    event_time = django_filters.DateFromToRangeFilter(field_name="event_time")
    ordering = django_filters.OrderingFilter(fields=("event_time", "event_type", "is_featured", "status"))

    class Meta:
        model = Event
        fields = ('event_type', 'is_featured', 'status')

    def filter_search(self, queryset, _, value):
        """
        Filter the queryset based on fuzzy search with priority-based inclusion
        Priority order for inclusion:
        1. Title match
        2. Description match
        3. Playlist match
        4. Presenter match
        5. Tag match

        Final results ordered by event_time (newest to oldest)
        """
        if not value:
            return queryset

        search_term = value.strip()
        similarity_threshold = 0.3

        playlist_match = Playlist.objects.filter(
            events=OuterRef('pk'),
            name__icontains=search_term
        )

        tag_match = Tag.objects.filter(
            events=OuterRef('pk'),
            name__icontains=search_term
        )

        presenter_match = EventPresenter.objects.filter(
            event=OuterRef('pk')
        ).annotate(
            full_name=Concat('user__first_name', Value(' '), 'user__last_name')
        ).filter(
            full_name__icontains=search_term
        )

        queryset = queryset.annotate(
            title_similarity=TrigramSimilarity('title', search_term),
            desc_similarity=TrigramSimilarity('description', search_term),
            has_playlist_match=Exists(playlist_match),
            has_tag_match=Exists(tag_match),
            has_presenter_match=Exists(presenter_match)
        )

        filtered_queryset = queryset.filter(
            Q(title__icontains=search_term) |
            Q(title_similarity__gt=similarity_threshold) |
            Q(description__icontains=search_term) |
            Q(desc_similarity__gt=similarity_threshold) |
            Q(has_playlist_match=True) |
            Q(has_presenter_match=True) |
            Q(has_tag_match=True)
        )

        if not filtered_queryset.exists():
            return queryset.none()

        return filtered_queryset.order_by('-event_time')

    def filter_tag(self, queryset, _, value):
        """ Filter the queryset based on the tag value """
        return queryset.filter(
            tags__name=value
        )

    def filter_playlist(self, queryset, _, value):
        """ Filter the queryset based on the playlist value """
        return queryset.filter(
            playlists__name=value
        )


class TagFilter(django_filters.rest_framework.FilterSet):
    """ Filter for the Tag model """

    linked_to_events = django_filters.BooleanFilter(method='filter_linked_to_events')

    class Meta:
        model = Tag
        fields = ['linked_to_events']

    def filter_linked_to_events(self, queryset, _, value):
        """ Filter the queryset based on the linked_to_events value """
        if value:
            return queryset.filter(events__isnull=False).distinct()
        return queryset


class PlaylistFilter(django_filters.rest_framework.FilterSet):
    """ Filter for the Playlist model """

    linked_to_events = django_filters.BooleanFilter(method='filter_linked_to_events')

    class Meta:
        model = Playlist
        fields = ['linked_to_events']

    def filter_linked_to_events(self, queryset, _, value):
        """ Filter the queryset based on the linked_to_events value """
        if value:
            return queryset.filter(events__isnull=False).distinct()
        return queryset
