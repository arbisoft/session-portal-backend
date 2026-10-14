```mermaid

erDiagram
    auth_User ||--o{ Event : creates
    Event |o--o{ VideoAsset : contains
    Event ||--o{ EventTag : has
    Tag ||--o{ EventTag : contains
    Event ||--o{ EventPlaylist : has
    Playlist ||--o{ EventPlaylist : contains
    Event ||--o{ EventPresenter : has
    auth_User ||--o{ EventPresenter : presents

    %% Todo: Add Workstream Integration tables
    %% Event ||--o| WorkstreamEvent : links_to
    %% WorkstreamEvent ||--|{ WorkstreamComment : has
    %% WorkstreamEvent ||--|{ WorkstreamRating : has

    auth_User {
        int id PK
        string username
        string email
        string password
        string first_name
        string last_name
        boolean is_active
        boolean is_staff
        boolean is_superuser
        datetime last_login
        datetime date_joined
    }

    Event {
        int id PK
        int creator_id FK
        string title
        string slug "nullable, set by post_save signal"
        text description
        datetime event_time
        string event_type
        string status
        string workstream_id "nullable"
        boolean is_featured
        datetime created
        datetime modified
    }

    VideoAsset {
        int id PK
        int event_id FK "nullable"
        string title
        string video_file "nullable"
        integer duration "seconds"
        string thumbnail "nullable"
        string status
        string captions_file "nullable"
        bigint file_size "bytes"
        integer view_count
        datetime created
        datetime modified
    }

    Tag {
        int id PK
        string name "unique"
        string description
        datetime created
        datetime modified
    }

    EventTag {
        int id PK
        int event_id FK
        int tag_id FK
    }

    Playlist {
        int id PK
        string name "unique"
        string description
        datetime created
        datetime modified
    }

    EventPlaylist {
        int id PK
        int event_id FK
        int playlist_id FK
    }

    EventPresenter {
        int id PK
        int event_id FK
        int user_id FK
    }

    %% WorkstreamEvent {
    %%     int id PK
    %%     string workstream_id
    %%     string title
    %%     text description
    %%     datetime event_date
    %%     string status
    %%     string requester_email
    %%     string presenter_email
    %%     datetime created_at
    %%     datetime updated_at
    %% }

    %% WorkstreamComment {
    %%     int id PK
    %%     int workstream_event_id FK
    %%     string author_email
    %%     text content
    %%     datetime created_at
    %%     datetime updated_at
    %% }

    %% WorkstreamRating {
    %%     int id PK
    %%     int workstream_event_id FK
    %%     string user_email
    %%     integer rating
    %%     datetime created_at
    %% }

```

## Notes

- The source of truth is `events/models.py`. Update this diagram in the same change as a model or migration.
- `EventTag` and `EventPlaylist` are the join tables Django generates for `Event.tags` and `Event.playlists` (`events_event_tags`, `events_event_playlists`); they are not separate models and have no timestamps.
- `EventPresenter` is an explicit model with `unique_together = (event, user)`.
- `event_type` is `SESSION`. `Event.status` is `DRAFT`, `PUBLISHED` or `ARCHIVED`, defaulting to `DRAFT`. `VideoAsset.status` is `PROCESSING`, `READY` or `FAILED`.
- A `VideoAsset` can exist without an event: the upload endpoint creates the asset first, and the event-creation endpoint attaches it.
- The explicit foreign keys (`Event.creator`, `VideoAsset.event`, `EventPresenter.event`, `EventPresenter.user`) use `on_delete=DO_NOTHING`.
- `VideoAsset.video_file` only accepts the `mp4`, `mov`, `avi` and `webm` extensions.
- `auth_User` is Django's built-in user model; the `users` app defines no models.
