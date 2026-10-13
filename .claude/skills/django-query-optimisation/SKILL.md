---
name: django-query-optimisation
description: N+1 and query-optimization patterns for Django and DRF in the Sessions Portal backend. Use when optimizing a view, queryset, or serializer; when adding select_related, prefetch_related, or annotate; when a SerializerMethodField or model property hits the database; or when a list endpoint is slow.
---

# Django & DRF Query Optimization

This skill provides a set of patterns and best practices for identifying and resolving N+1 query issues, particularly when working with Django Rest Framework (DRF) list views.


## 1. Bulk Fetching Patterns

### select_related
Use `select_related` for "forward" relationships (ForeignKey, OneToOne) where the record count is 1:1 or N:1. This uses an SQL `JOIN`.

```python
# In ViewSet
def get_queryset(self):
    return Event.objects.select_related('creator').prefetch_related('videos')
```

### prefetch_related
Use `prefetch_related` for "reverse" relationships (ForeignKey back-refs) or "many-to-many" relationships. This executes separate queries and joins them in Python.

```python
# In ViewSet
def get_queryset(self):
    return Event.objects.prefetch_related('tags', 'playlists', 'presenters')
```

### Prefetch Objects
Use `Prefetch` objects to further optimize pre-fetched data (e.g., filtering or ordering the related queryset).

```python
from django.db.models import Prefetch

def get_queryset(self):
    recent = Tag.objects.order_by('-id')
    return Event.objects.prefetch_related(
        Prefetch('tags', queryset=recent, to_attr='recent_tags')
    )
```

## 2. Advanced Resolution Patterns

### Bulk Lookup Map Pattern
When a simple `prefetch_related` isn't enough (e.g., complex logic or external utility calls), fetch the data for all IDs once and use a dictionary for O(1) lookups in the loop.

```python
# In View or Utility
view_counts = dict(
    VideoAsset.objects.filter(event_id__in=event_ids).values_list('event_id', 'view_count')
)

def get_view_count(event):
    return view_counts.get(event.id, 0)
```

### Passing Pre-fetched Data via Context
Standardize data access by passing pre-fetched maps or utility instances through the serializer `context`. This avoids re-fetching in `SerializerMethodField`.

### Instance-level Memoization in Serializers
If multiple `SerializerMethodFields` depend on the same complex calculation or related queryset, cache the result on the serializer instance to avoid redundant database hits or CPU work.

```python
class EventSerializer(serializers.ModelSerializer):
    tag_count = serializers.SerializerMethodField()
    tag_names = serializers.SerializerMethodField()

    def _tags(self, obj):
        return list(obj.tags.all())

    def get_tag_count(self, obj):
        return len(self._tags(obj))

    def get_tag_names(self, obj):
        return [tag.name for tag in self._tags(obj)]
```

## 3. Serializer Best Practices

### Prefer SerializerMethodField over Model Properties
If a model property (e.g., `@property def is_active(self):`) performs a database query (like `.exists()` or `.filter()`), it will trigger an N+1 issue in a list view.

**Solution:**
1.  Add the necessary `prefetch_related` in the `get_queryset` method of the ViewSet.
2.  Define a `SerializerMethodField` in the serializer.
3.  Access the pre-fetched data using `.all()` (which hits the cache) instead of `.filter()` (which hits the DB).

```python
# Model
class Event(models.Model):
    @property
    def has_presenters(self):
        return self.presenters.filter(first_name__gt='').exists()

class EventSerializer(serializers.ModelSerializer):
    has_presenters = serializers.SerializerMethodField()

    def get_has_presenters(self, instance):
        return any(presenter.first_name for presenter in instance.presenters.all())
```

## 4. Contextual Data Passing

Avoid fetching global or semi-static data (like the requesting user's own event IDs) per item. Fetch it once in the view and pass it via `serializer.context`.

```python
# View
def get_serializer_context(self):
    context = super().get_serializer_context()
    context['user_event_ids'] = set(self.request.user.events.values_list('id', flat=True))
    return context

# Serializer
def get_is_mine(self, instance):
    return instance.id in self.context['user_event_ids']
```

## 5. Common Pitfalls

### The `.filter()` on Related Managers Trap
**NEVER** call `.filter()` or `.exclude()` on a related manager inside a loop (like a serializer) if you expect to use pre-fetched data. These methods **always** hit the database.

**Bad:**
```python
def get_active_items(self, obj):
    return obj.tags.filter(name__startswith='a').all()
```

**Good:**
```python
# 1. In ViewSet: use Prefetch
queryset.prefetch_related(Prefetch('tags', queryset=Tag.objects.filter(name__startswith='a')))

# 2. In Serializer: use .all()
def get_active_items(self, obj):
    return obj.tags.all()
```

### Aggregates in Loops
Calling `.aggregate()` (e.g., `Sum`, `Avg`) inside a loop is an N+1 issue.

**Solution:** 
- Use `annotate()` on the main queryset to perform the calculation in the same SQL query.
- If too complex for `annotate()`, use the **Bulk Lookup Map Pattern** with a manual aggregate query (`values('group_field').annotate(total=Sum('value'))`).

## 6. Project Hot Spots

- Event serializers walk `creator` (FK), `tags` / `playlists` / `presenters` (M2M), and `videos` (reverse FK from `VideoAsset.event`). Methods that call `event.videos.first()` or filter `EventPresenter` per event are per-row queries; read from a prefetch with `.all()` instead.
- `VideoAsset.save()` runs ffmpeg; use `QuerySet.update()` for counters and status columns (`VideoAssetIncrementViewCountView`).
- The event list is trigram search (`EventFilter.filter_search`); keep new filters composable with it and avoid per-row subqueries.

## 7. Optimization Checklist

- [ ] **FK / OneToOne walked per row?** `select_related`.
- [ ] **M2M / reverse FK walked per row?** `prefetch_related` (use `Prefetch` to filter).
- [ ] **`.filter()` / `.exists()` on a related manager in a serializer?** Switch to `.all()` over a prefetch.
- [ ] **Same calculation in several method fields?** Memoize on the serializer instance.
- [ ] **Global or per-request data?** Fetch once, pass via `context`.
- [ ] **Aggregate in a loop?** `annotate()` or a bulk lookup map.
- [ ] **Batch writes?** `bulk_create` / `bulk_update`.
- [ ] **Verify** with `assertNumQueries` / `django_assert_num_queries` in a test when fixing an N+1.
