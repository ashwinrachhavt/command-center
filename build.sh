#!/bin/bash

# Exit if any command fails
set -e

echo "Starting Django build process for Vercel..."

# Change to the backend directory
cd command-center-backend

echo "Installing Python dependencies..."
# Install Python dependencies with upgraded pip
pip install --upgrade pip
pip install -r requirements.txt

echo "Collecting static files..."
# Run Django's collectstatic with verbose output
python manage.py collectstatic --noinput --verbosity=1

echo "Running database migrations..."
# Run migrations (this will create SQLite database if it doesn't exist)
python manage.py migrate --noinput

echo "Creating superuser if it doesn't exist..."
# Create a superuser if none exists (for admin access)
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(is_superuser=True).exists():
    try:
        User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
        print('✓ Superuser created successfully')
    except Exception as e:
        print(f'Warning: Could not create superuser: {e}')
else:
    print('✓ Superuser already exists')
"

echo "Checking Django configuration..."
# Quick Django check
python manage.py check --deploy

echo "✓ Build process completed successfully!"
echo "Your Django app is ready for deployment!"
echo "Access your app at: https://your-project-name.vercel.app"
echo "Admin interface: https://your-project-name.vercel.app/admin"
echo "API endpoint: https://your-project-name.vercel.app/api"