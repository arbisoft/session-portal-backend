#!/bin/sh

echo "Running Database Migrations"
python manage.py migrate

exec "$@"
