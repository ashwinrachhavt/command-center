#!/bin/bash

# Exit if any command fails
set -e

# Change to the backend directory
cd command-center-backend

# Install Python dependencies
pip install -r requirements.txt

# Run Django's collectstatic
python manage.py collectstatic --no-input