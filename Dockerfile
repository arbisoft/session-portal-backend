FROM python:3.12-slim AS base

ARG UID=1000
ARG GID=1000

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
    && apt-get clean all \
    && rm -rvf /var/lib/apt/* /var/cache/apt/* \
    && find / -type d -name "__pycache__" -exec rm -rv {} + 2>/dev/null || true

ENV VIRTUAL_ENV="/app_venv"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN \
    groupadd -fg $GID app \
    && useradd -m --shell /bin/false -r -u $UID -g app app

RUN python3 -m venv "${VIRTUAL_ENV}"

WORKDIR /app

FROM base AS app_venv_production

COPY requirements/base.txt /tmp/requirements/base.txt
RUN pip install --no-cache-dir --no-compile -r /tmp/requirements/base.txt \
    && pip install --no-cache-dir --no-compile gunicorn

FROM base AS app

COPY --from=app_venv_production ${VIRTUAL_ENV} ${VIRTUAL_ENV}

COPY . /app/

RUN chmod +x entrypoint.sh

USER app

FROM base AS dev

COPY --from=app_venv_production ${VIRTUAL_ENV} ${VIRTUAL_ENV}

COPY requirements/dev.txt /tmp/requirements/dev.txt

RUN pip install --no-cache-dir  --no-compile -r /tmp/requirements/dev.txt

USER app
