#!/bin/sh
set -eu
python manage.py wait_for_db
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec gunicorn config.wsgi:application --config deploy/gunicorn.conf.py

