# Complete Vercel Deployment Guide

## Overview
This guide provides step-by-step instructions for deploying your Django Command Center to Vercel with all the necessary fixes applied.

## Prerequisites
- ✅ Vercel account
- ✅ Git repository with your code
- ✅ External database (see DATABASE_SETUP.md)

## Step-by-Step Deployment

### 1. Prepare Your Database
**⚠️ CRITICAL:** SQLite won't work on Vercel. You MUST use an external database.

Choose one of these options:

#### Option A: Vercel Postgres (Recommended)
1. Go to Vercel Dashboard → Storage → Create Database
2. Select PostgreSQL
3. Follow the setup wizard
4. Copy the `DATABASE_URL` from the dashboard

#### Option B: Supabase (Free Tier)
1. Sign up at [supabase.com](https://supabase.com)
2. Create a new project
3. Go to Settings → Database
4. Copy the connection string (URI format)

#### Option C: Other Options
See `DATABASE_SETUP.md` for Railway, PlanetScale, and other database options.

### 2. Generate Required Environment Variables

#### Generate Secret Key
Run this command to generate a secure secret key:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

#### Prepare Environment Variables
You'll need these variables (copy the example from `command-center-backend/env.example`):

```bash
# Required
SECRET_KEY=your-generated-secret-key
DEBUG=False
ALLOWED_HOSTS=.vercel.app
DATABASE_URL=your-database-url-here

# Optional (if using AI features)
OPENAI_API_KEY=your-openai-api-key
LANGCHAIN_API_KEY=your-langchain-api-key
```

### 3. Configure Vercel Environment Variables
1. Go to your Vercel Dashboard
2. Select your project (or create it if first deployment)
3. Go to Settings → Environment Variables
4. Add each variable from step 2

### 4. Deploy Your Application
1. Push your code to your Git repository
2. Vercel will automatically detect the changes and start deployment
3. The build process will:
   - Run `bash build.sh` (installs dependencies and collects static files)
   - Create serverless functions for your Django app
   - Set up static file serving

### 5. Post-Deployment Setup

#### Run Database Migrations
After your first successful deployment, you need to run migrations:

**Option A: Using Vercel CLI**
```bash
# Install Vercel CLI if you haven't
npm install -g vercel

# Run migrations
vercel --prod exec -- python command-center-backend/manage.py migrate
```

**Option B: Using a temporary migration endpoint**
1. Temporarily add this to your `urls.py`:
```python
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
    path("run-migrations/", run_migrations, name="run_migrations"),
]
```

2. Visit `https://your-project.vercel.app/run-migrations/`
3. Remove the migration endpoint after use

#### Create Superuser
After migrations are complete:

**Option A: Using Vercel CLI**
```bash
vercel --prod exec -- python command-center-backend/manage.py createsuperuser
```

**Option B: Using Django Shell**
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

### 6. Access Your Application
Your Django app will be available at:
- **Main App**: `https://your-project-name.vercel.app` (redirects to admin)
- **Admin Interface**: `https://your-project-name.vercel.app/admin`
- **API Status**: `https://your-project-name.vercel.app/api`

## Troubleshooting

### Common Issues and Solutions

#### 1. Build Failures
**Issue**: Build fails with dependency errors
**Solution**: 
- Check `requirements.txt` has all necessary packages
- Verify Python version compatibility
- Check build logs in Vercel dashboard

#### 2. Database Connection Errors
**Issue**: "DATABASE_URL is required" error
**Solution**:
- Verify `DATABASE_URL` is set in Vercel environment variables
- Test database connection independently
- Check database URL format

#### 3. Static Files Not Loading
**Issue**: CSS/JS files return 404
**Solution**:
- Verify `collectstatic` runs during build
- Check static files path in `vercel.json`
- Ensure WhiteNoise is properly configured

#### 4. Function Timeout Errors
**Issue**: Serverless function times out
**Solution**:
- Check for long-running operations in views
- Optimize database queries
- Consider using async operations

### Testing Your Deployment

#### Test Database Connection
Add this temporary view to test your database:
```python
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

Visit `https://your-project.vercel.app/test-db/` to test.

#### Test Static Files
Check that your admin interface loads with proper styling at:
`https://your-project.vercel.app/admin`

## Configuration Files Reference

### vercel.json
```json
{
  "version": 2,
  "builds": [
    {
      "src": "command-center-backend/command_center/wsgi.py",
      "use": "@vercel/python",
      "config": {
        "maxLambdaSize": "15mb",
        "runtime": "python3.11"
      }
    },
    {
      "src": "command-center-backend/staticfiles/**",
      "use": "@vercel/static"
    }
  ],
  "routes": [
    {
      "src": "/static/(.*)",
      "dest": "/command-center-backend/staticfiles/$1"
    },
    {
      "src": "/(.*)",
      "dest": "command-center-backend/command_center/wsgi.py"
    }
  ],
  "installCommand": "bash build.sh",
  "buildCommand": "echo 'Build completed via build.sh'",
  "env": {
    "PYTHONPATH": "command-center-backend"
  }
}
```

### Key Django Settings
- `DEBUG=False` (production mode)
- `ALLOWED_HOSTS` includes `.vercel.app`
- External database configuration
- WhiteNoise for static files
- Production security settings

## Security Checklist
- [ ] `DEBUG=False` in production
- [ ] Strong, unique `SECRET_KEY`
- [ ] Secure database credentials
- [ ] HTTPS-only cookies
- [ ] Proper CORS configuration
- [ ] Regular security updates

## Next Steps
1. Set up monitoring and logging
2. Configure custom domain (if needed)
3. Set up CI/CD pipeline
4. Add environment-specific settings
5. Configure backup strategies for your database

## Support
- Check Vercel deployment logs for detailed error messages
- Review Django deployment documentation
- See `DATABASE_SETUP.md` for database-specific issues
- Test locally with production settings before deploying

Your Django Command Center is now ready for production on Vercel! 🚀 