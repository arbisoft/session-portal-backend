# Arbisoft Sessions Portal
[![python](https://img.shields.io/badge/Python-FFD43B?style=for-the-badge&logo=python&logoColor=blue)](https://www.python.org) [![Django](https://img.shields.io/badge/Django-092E20?style=for-the-badge&logo=django&logoColor=green)](https://docs.djangoproject.com/en/4.2/) [![PostgresSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)](https://formulae.brew.sh/formula/postgresql@16)

Backend for Arbisoft's internal Sessions Portal: recorded sessions (events) with video, tags, playlists, and presenters.
Built with Django 4.2 and Django REST Framework on PostgreSQL. Celery and Redis are used to import videos from Google Drive and to finalize resumable uploads.

Setup guide to set up the project from scratch.

- Covered OS:
    * macOS
- Table of Contents
  * [Prerequisites](#prerequisites)
  * [Set up Environment Variables](#set-up-environment-variables)
  * [Code setup](#code-setup)
  * [Option 1: Setup Using Virtual Environment](#option-1-setup-using-virtual-environment)
    + [Python 3.12](#python-312)
      - [Install pyenv](#install-pyenv)
      - [Install Python 3.12](#install-python-312)
    + [PIP](#pip)
    + [PostgreSQL](#postgresql)
      - [Install using brew](#install-using-brew)
      - [Start service](#start-service)
    + [ffmpeg](#ffmpeg)
    + [Install, Create and Activate Virtual Environment](#install-create-and-activate-virtual-environment)
      - [Install pyenv-virtualenv](#install-pyenv-virtualenv)
    + [Install dependencies](#install-dependencies)
    + [Database setup](#database-setup)
    + [Migrate](#migrate)
    + [Run server](#run-server)
    + [Redis and Celery](#redis-and-celery)
    + [Run tests](#run-tests)
    + [Run linting](#run-linting)
  * [Option 2: Set Up Using Docker](#option-2-set-up-using-docker)
    + [Docker prerequisites](#docker-prerequisites)
    + [Build and Start Docker Containers](#build-and-start-docker-containers)
    + [Run Linting in Docker](#run-linting-in-docker)
    + [Run Tests in Docker](#run-tests-in-docker)
  * [API documentation](#api-documentation)
  * [Django admin](#django-admin)
  * [Management commands](#management-commands)
  * [CI and deployment](#ci-and-deployment)
  * [More documentation](#more-documentation)

## Prerequisites
| Requirement | Needed for |
| --- | --- |
| Python 3.12 | Everything |
| PostgreSQL 16 | Everything. SQLite does not work: search uses `django.contrib.postgres` trigram similarity |
| ffmpeg | Every video upload. `VideoAsset.save()` runs ffmpeg synchronously to read the duration and extract a thumbnail |
| Redis and a Celery worker | Google Drive video imports and finalizing resumable uploads. The single-request upload does not need them |
| Docker and docker-compose | Option 2 only |

## Set up Environment Variables
Create `.env` file at the root of the project from the following and set the variables:
```bash
DB_NAME=asp
DB_USER=<your postgres user>
DB_PASSWORD=<your postgres password>
DB_HOST=<your postgres host>
DB_PORT=5432

DJANGO_PORT=<django server port>
DJANGO_SECRET_KEY=<django secret key>
DJANGO_DEBUG=<django debug flag>
```

| Variable | Read by | Notes |
| --- | --- | --- |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | `settings/local.py` (copied from `local.example.py`), `settings/test.py`, and `docker-compose.yml` | `settings/base.py` hardcodes an empty database user, so the server needs `local.py` to connect. Use `DB_HOST=localhost` for Option 1 and `DB_HOST=db` for Option 2. `docker-compose.yml` uses only `DB_USER`, `DB_PASSWORD` and `DB_NAME`. `settings/test.py` falls back to `testdb` / `testuser` / `testpassword` / `localhost` / `5432` when a variable is unset |
| `DJANGO_SECRET_KEY` | `settings/base.py` | No default. Tests use their own key |
| `DJANGO_DEBUG` | `settings/base.py` | Any non-empty value, including `False`, turns debug on. Leave it unset to turn it off. `ALLOWED_HOSTS` is empty, so `runserver` refuses to start with debug off: set it for local development. Debug also serves `/media/` files |
| `DJANGO_PORT` | `docker-compose.yml` only | Port that `runserver` binds and that the `django` container publishes. With Option 1, `runserver` uses its own default (8000) |
| `RESUMABLE_UPLOAD_*` | `settings/base.py` | Optional limits and locations for resumable uploads (file size, chunk size, session TTL, partial-file directory). Defaults and meaning are in the Settings table of [UPLOADS.md](UPLOADS.md) |
| `SENTRY_DSN` | `settings/base.py` | Sentry error reporting is off when this is unset. Initialised by `arbisoft_sessions_portal/sentry.py` when the project package is imported (web, Celery worker and beat, `manage.py`), from the final `settings.SENTRY_DSN`, so `settings/local.py` can override it and `settings/test.py` sets it to `None` (tests never create a client) |
| `SENTRY_ENVIRONMENT` | `settings/base.py` | Optional environment name shown in Sentry (for example `production`) |
| `SENTRY_TRACES_SAMPLE_RATE` | `settings/base.py` | Fraction of requests and tasks traced, from `0.0` to `1.0`. Defaults to `0.0` |
| `SENTRY_PROFILE_SESSION_SAMPLE_RATE` | `settings/base.py` | Fraction of sessions profiled, from `0.0` to `1.0`. Defaults to `0.0` |

Do not commit `.env` or `local.py`; both are gitignored.

## Code setup
### Create local.py file
On root of your project run the command
```bash
$ cp arbisoft_sessions_portal/settings/local.example.py arbisoft_sessions_portal/settings/local.py
```
`local.py` reads the `DB_*` variables from `.env`. It is also the place to override any other setting for your machine, such as the Celery broker URL (see [Redis and Celery](#redis-and-celery)).

## Option 1: Setup Using Virtual Environment
### Python 3.12
#### Install pyenv
```bash
$ brew install pyenv
$ echo 'eval "$(pyenv init -)"' >> ~/.zshrc
$ source ~/.zshrc
```
#### Install Python 3.12
```bash
$ pyenv install 3.12
```
### PIP
Install pip3 by running:
```bash
$ curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
$ python get-pip.py
```
### PostgreSQL
#### Install using brew
```bash
$ brew install postgresql@16
```
#### Start service
```bash
$ brew services start postgresql@16
```

### ffmpeg
```bash
$ brew install ffmpeg
```

### Install, Create and Activate Virtual Environment
#### Install pyenv-virtualenv
Install pyenv-virtualenv with homebrew and add its init to your .zshrc
```bash
$ brew install pyenv-virtualenv
$ echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.zshrc
$ source ~/.zshrc
```
Create a virtual environment (with Python 3.12.6) for the asp project and activate it:
```bash
$ pyenv virtualenv 3.12.6 venv-3.12.6
```
You can set it as default for the repo (activated each time you enter the project's directory). Execute the following from the root of the repo:
```bash
$ pyenv local venv-3.12.6
```
Or, alternatively, you can activate it manually and work while it is on:
```bash
$ pyenv activate venv-3.12.6
```
### Install dependencies
At project root run the following command to install dependencies:
```bash
$ pip install -r requirements/base.txt
```
To run the tests or the linters, also install the development dependencies. `dev.txt` does not include `base.txt`, so install both:
```bash
$ pip install -r requirements/base.txt -r requirements/dev.txt
```
### Database setup
Create a new database using command
```bash
$ createdb asp
```

### Migrate
Apply the migrations
```bash
$ python manage.py migrate
```
Migration `events/0011_add_pg_trgm_extension` runs `CREATE EXTENSION pg_trgm`, so the database user must be allowed to create extensions.

### Run server
Run the server
```bash
$ python manage.py runserver
```
`DJANGO_DEBUG` must be set in `.env` (see [Set up Environment Variables](#set-up-environment-variables)), otherwise `runserver` exits with "You must set settings.ALLOWED_HOSTS if DEBUG is False."

### Redis and Celery
These are needed by the Google Drive import (the "Google Drive Link" field on a video asset in the Django admin, and `prepopulate_events`) and by resumable uploads, whose finalization step runs as a Celery task. The older single-request upload endpoint does not need them.

Start Redis and a Celery worker:
```bash
$ brew install redis
$ brew services start redis
$ celery -A arbisoft_sessions_portal worker -l info
```
`settings/base.py` points `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` at `redis://redis:6379/0`, the Docker hostname. Outside Docker, override both in `local.py`:
```python
CELERY_BROKER_URL = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = "redis://localhost:6379/0"
```

### Run tests
The tests need a reachable PostgreSQL. They read the `DB_*` variables from the environment and from `.env`, so with the `.env` above they connect with your own credentials and Django creates a separate `test_<DB_NAME>` database. If `DB_*` is not set anywhere (as in CI), they fall back to `testuser` / `testpassword` on `localhost:5432` with database `testdb`.
```bash
$ pytest --cov --cov-report=term
```
Coverage must stay at or above 80%. Run a single test with `pytest events/tests/test_apis.py::TestClassName::test_name`.

### Run linting
This is what CI runs (pylint, pycodestyle and an isort check over `events` and `users`):
```bash
$ tox -e quality
```
To fix import ordering automatically:
```bash
$ tox -e isort
```

## Option 2: Set Up Using Docker

### Docker prerequisites
Before you begin, ensure that you have the following installed:

- Docker: https://docs.docker.com/engine/install/ubuntu/
- docker-compose: https://docs.docker.com/compose/install/

Create `.env` and `local.py` as described above, with `DB_HOST=db`. They are not copied into the image (see `.dockerignore`); the containers get them from the `.:/app` bind mount.

### Build and Start Docker Containers
This command will rebuild and start all the services using the configuration defined in docker-compose.yml: `db` (PostgreSQL 16), `redis`, `celery`, `celery-beat`, and `django`. The `django` container runs `python manage.py migrate` through `entrypoint.sh` before starting the server.

```bash
export GID=$(id -g)
export UID=$(id -u)
docker-compose up --build 
```
In bash `UID` is read-only, so `export UID=...` fails. Use `export GID=$(id -g)` followed by `export UID` instead.

Once the containers are up, check the API connection by visiting http://localhost:${DJANGO_PORT} to ensure the Django app is running properly.

### Run Linting in Docker
To run linting for the project, use the following command:

```bash
docker-compose --profile dev up lint
```

### Run Tests in Docker
To run test for the project, use the following command:

```bash
docker-compose --profile dev up test
```
The `test` container reads `DB_*` from the bind-mounted `.env`, so `DB_HOST=db` must be set there.

## API documentation
The API reference is generated from the code (drf-spectacular). With the server running:

- Swagger UI: `/api/docs/`
- ReDoc: `/api/redoc/`
- OpenAPI schema: `/api/schema/`

Endpoints live under `/api/v1/users/` and `/api/v1/events/`. Large-file uploads use the resumable endpoints under `/api/v1/events/videoassets/`, documented in [UPLOADS.md](UPLOADS.md). Every endpoint requires a JSON Web Token (JWT) or a session login except the two login endpoints; staff-only endpoints also require `is_staff`.

## Django admin
Create a superuser, then sign in at `/admin/`:
```bash
$ python manage.py createsuperuser
```
Staff access to the upload and event-creation endpoints is controlled by a user's `is_staff` flag, which you set in the admin. Users created through Google login are not staff.

## Management commands
```bash
$ python manage.py check_videoasset_status [ASSET_ID ...] [--all] [--recent HOURS] [--processing]
$ python manage.py prepopulate_events CSV_FILE [--dry-run] [--skip-video-download] [--creator USERNAME]
$ python manage.py cleanup_upload_sessions
```
- `check_videoasset_status` prints the status of video assets. Pass asset IDs, `--all`, or `--recent HOURS`; `--processing` narrows the output to processing and failed assets.
- `cleanup_upload_sessions` expires abandoned resumable uploads and deletes their leftovers. Celery beat runs it hourly; see [UPLOADS.md](UPLOADS.md).
- `prepopulate_events` imports events from a CSV with the columns `Title`, `Details`, `Trainer`, `Publish Date`, `Link`, `Playlist`, and `Tags`. It queues the Google Drive downloads on Celery, so Redis and a worker must be running unless you pass `--skip-video-download`. Use `--dry-run` first.

## CI and deployment
- `.github/workflows/ci.yml` runs on pushes to `main` and on every pull request: `tox` with the `quality` environment, then `pytest --cov --cov-report=term`.
- `.github/workflows/build-and-push-container-image.yml` runs when a GitHub release is published (or when started manually). It builds the `app` image target, pushes it to AWS ECR, and triggers the backend deployment workflow.

## More documentation
- `CLAUDE.md`: commands, architecture, and the traps that are easy to hit.
- `.claude/rules/`: coding standards, testing rules, security rules, and the branching and pull request workflow. `.claude/rules/README.md` indexes them.
- `DATABASE_DESIGN.md`: entity-relationship diagram of the schema.
