#!/bin/bash

# Exit if any command fails
set -e

echo "Starting Django build process..."

# Change to the backend directory
cd command-center-backend

echo "Installing Python dependencies..."
# Install Python dependencies with upgraded pip
pip install --upgrade pip
pip install -r requirements.txt

echo "Collecting static files..."
# Run Django's collectstatic with verbose output
python manage.py collectstatic --noinput --verbosity=2

echo "Running database migrations..."
# Run migrations (this will create SQLite database if it doesn't exist)
python manage.py migrate --noinput

echo "Creating superuser if it doesn't exist..."
# Create a superuser if none exists (for admin access)
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
    print('Superuser created')
else:
    print('Superuser already exists')
"

echo "Build process completed successfully!"