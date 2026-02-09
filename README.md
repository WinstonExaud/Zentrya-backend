# Zentrya Admin Backend

A comprehensive FastAPI backend for managing a streaming platform.

## Quick Start

### Using Docker (Recommended)

1. **Start services**:
   ```bash
   docker-compose up -d
   ```

2. **Run migrations**:
   ```bash
   docker-compose exec api alembic upgrade head
   ```

3. **Create admin user**:
   ```bash
   docker-compose exec api python -m app.initial_data
   ```

4. **Access the API**:
   - API: http://localhost:8000
   - Docs: http://localhost:8000/docs

### Manual Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Setup database** (PostgreSQL required):
   ```bash
   createdb zentrya_db
   alembic upgrade head
   ```

3. **Start Redis** (Redis required):
   ```bash
   redis-server
   ```

4. **Run application**:
   ```bash
   uvicorn app.main:app --reload
   ```

## Default Admin Credentials

- Email: admin@zentrya.com
- Password: admin123

**⚠️ Change these in production!**

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Features

- 🔐 JWT Authentication & Authorization
- 🎬 Movie & Series Management
- 📱 Episode Management
- 📂 Category Management
- 👥 User Management
- 📊 Analytics & Insights
- 💾 File Upload (Local/S3)
- ⚡ Redis Caching
- 📈 View History Tracking
