# Database Setup Guide for Vercel Deployment

## Overview

Vercel's serverless functions are **ephemeral** - they don't persist data between requests. This means SQLite won't work for production deployment. You need an external database.

## Recommended Database Options

### 1. **Vercel Postgres** (Recommended)
- **Pros**: Integrated with Vercel, easy setup, good performance
- **Cons**: Paid service
- **Setup**: 
  1. Go to Vercel Dashboard → Storage → Create Database
  2. Select PostgreSQL
  3. Follow the setup wizard
  4. Copy the `DATABASE_URL` from the dashboard

### 2. **Supabase** (Free Tier Available)
- **Pros**: Free tier, PostgreSQL, includes additional features
- **Cons**: External service
- **Setup**:
  1. Sign up at [supabase.com](https://supabase.com)
  2. Create a new project
  3. Go to Settings → Database
  4. Copy the connection string (URI format)

### 3. **PlanetScale** (MySQL)
- **Pros**: Free tier, MySQL, good performance
- **Cons**: MySQL instead of PostgreSQL
- **Setup**:
  1. Sign up at [planetscale.com](https://planetscale.com)
  2. Create a new database
  3. Create a password
  4. Copy the connection string

### 4. **Railway**
- **Pros**: Simple setup, PostgreSQL, good free tier
- **Cons**: External service
- **Setup**:
  1. Sign up at [railway.app](https://railway.app)
  2. Create a PostgreSQL database
  3. Copy the connection string

## Database URL Format

Your `DATABASE_URL` should be in one of these formats:

### PostgreSQL:
```
postgresql://username:password@host:port/database_name
```

### MySQL:
```
mysql://username:password@host:port/database_name
```

## Setting Up Your Database

### Step 1: Choose and Set Up Your Database
Choose one of the options above and create your database.

### Step 2: Add Environment Variables to Vercel
1. Go to your Vercel Dashboard
2. Select your project
3. Go to Settings → Environment Variables
4. Add these variables:

```bash
# Required
SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=.vercel.app
DATABASE_URL=your-database-url-here

# Optional (for features that need them)
OPENAI_API_KEY=your-openai-api-key
LANGCHAIN_API_KEY=your-langchain-api-key
```

### Step 3: Generate a Secure Secret Key
Run this command to generate a secure secret key:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Step 4: Deploy and Run Migrations
1. Push your code to trigger a new deployment
2. After deployment, run migrations using one of these methods:

#### Option A: Using Vercel CLI
```bash
# Install Vercel CLI if you haven't
npm install -g vercel

# Run migrations
vercel --prod exec -- python command-center-backend/manage.py migrate
```

#### Option B: Create a Django Management Command
Create a simple view to run migrations (temporary, remove after use):

```python
# In command-center-backend/command_center/urls.py
from django.http import JsonResponse
from django.core.management import call_command

def run_migrations(request):
    try:
        call_command('migrate')
        return JsonResponse({"status": "success", "message": "Migrations completed"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})

# Add to urlpatterns temporarily
urlpatterns = [
    # ... existing patterns ...
    path("run-migrations/", run_migrations, name="run_migrations"),  # Remove after use!
]
```

Then visit `https://your-project.vercel.app/run-migrations/` once.

### Step 5: Create a Superuser
After migrations are complete, create a superuser:

#### Option A: Using Vercel CLI
```bash
vercel --prod exec -- python command-center-backend/manage.py createsuperuser
```

#### Option B: Create via Django Shell
```bash
vercel --prod exec -- python command-center-backend/manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'your-secure-password')
    print('Superuser created')
else:
    print('Superuser already exists')
"
```

## Troubleshooting

### Common Issues

1. **"DATABASE_URL is required" Error**
   - Make sure `DATABASE_URL` is set in Vercel environment variables
   - Verify the database URL format is correct

2. **Connection Refused**
   - Check that your database is running
   - Verify the hostname, port, and credentials
   - Ensure your database allows connections from Vercel IPs

3. **SSL Certificate Issues**
   - Add `?sslmode=require` to your PostgreSQL URL
   - For older databases, try `?sslmode=disable` (not recommended for production)

4. **Migration Errors**
   - Make sure your database exists and is accessible
   - Check that your app has proper permissions to create tables
   - Review migration files for any issues

### Testing Your Database Connection

Create a simple test view to verify your database connection:

```python
# In urls.py (temporary)
from django.db import connection
from django.http import JsonResponse

def test_db(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
        return JsonResponse({"status": "success", "database": "connected"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})
```

Visit `https://your-project.vercel.app/test-db/` to test the connection.

## Security Best Practices

1. **Never commit database credentials to Git**
2. **Use environment variables for all sensitive data**
3. **Use SSL/TLS for database connections**
4. **Regularly rotate your database passwords**
5. **Use strong, unique passwords for database users**
6. **Limit database user permissions to only what's needed**

## Next Steps

Once your database is set up:
1. Test the connection
2. Run migrations
3. Create a superuser
4. Access your admin interface
5. Start using your Django app!

Your Command Center should now be fully functional with persistent data storage. 