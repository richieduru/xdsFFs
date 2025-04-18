#!/usr/bin/env bash
set -e

# Install Python deps
pip install -r requirements.txt

# Apply migrations
python manage.py migrate --noinput

# Collect static files
python manage.py collectstatic --noinput
