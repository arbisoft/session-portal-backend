FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED 1

WORKDIR /app
COPY . /app/

RUN pip install --no-cache-dir -r requirements/base.txt

FROM base AS app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh


FROM base AS dev
RUN pip install --no-cache-dir -r requirements/dev.txt
