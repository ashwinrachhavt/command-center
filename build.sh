#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -o errexit

# Install project dependencies
pip install -r requirements.txt

# Run collectstatic
python manage.py collectstatic --no-input