#!/bin/bash

# Exit if any command fails
set -e

echo "Starting Django build process for Vercel serverless deployment..."

# Change to the backend directory
cd command-center-backend

echo "Installing Python dependencies..."
# Install Python dependencies with upgraded pip
pip install --upgrade pip
pip install -r requirements.txt

echo "Collecting static files..."
# Run Django's collectstatic with verbose output
# Note: This creates static files that will be served by Vercel's static hosting
python manage.py collectstatic --noinput --verbosity=1

echo "Checking Django configuration..."
# Quick Django check (skip database checks since we don't have DB at build time)
python manage.py check --deploy --skip-checks=database

echo "✓ Build process completed successfully!"
echo ""
echo "📋 IMPORTANT: Post-deployment setup required:"
echo "1. Set up an external database (PostgreSQL recommended)"
echo "2. Add DATABASE_URL to Vercel environment variables"
echo "3. After first deployment, run migrations manually:"
echo "   - Visit https://your-project.vercel.app/admin (will show error until DB is set up)"
echo "   - Or use Vercel CLI: vercel env add DATABASE_URL"
echo ""
echo "🔗 Your app will be available at:"
echo "   - Main: https://your-project-name.vercel.app"
echo "   - Admin: https://your-project-name.vercel.app/admin"
echo "   - API: https://your-project-name.vercel.app/api"