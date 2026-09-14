#!/bin/sh
set -eu
python manage.py wait_for_db
python manage.py migrate --noinput
exec python manage.py runserver 0.0.0.0:8000

